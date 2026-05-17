"""
AgentPass Merchant — agentpass.json 取得・検証クローラー

ai-instructions.md セクション4 のスキーマに完全準拠。
Pydantic v2 で厳格にバリデーションし、異常時は MerchantUnverifiedError を送出。

HTTP取得ロジックは _fetch 引数で差し替え可能にしてあるため、
テストでは外部通信なしでモック関数を注入できる。
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

# AgentPassがサポートするバージョン集合（将来の後方互換を管理）
SUPPORTED_VERSIONS: frozenset[str] = frozenset({"1.0"})

# Ed25519 公開鍵のバイト長
_ED25519_PUBLIC_KEY_BYTES = 32

# デフォルトの HTTP タイムアウト（秒）
_DEFAULT_TIMEOUT = 10


# ---------------------------------------------------------------------------
# 例外クラス（ai-instructions.md セクション7 に対応）
# ---------------------------------------------------------------------------

class MerchantUnverifiedError(Exception):
    """503 MERCHANT_UNVERIFIED — agentpass.json が存在しないか無効"""
    http_status = 503
    error_code = "MERCHANT_UNVERIFIED"


# ---------------------------------------------------------------------------
# Pydantic スキーマ（ai-instructions.md セクション4 完全準拠）
# ---------------------------------------------------------------------------

class PricingEntry(BaseModel):
    """加盟店が公開するエンドポイント単位の価格情報。"""

    model_config = {"extra": "ignore"}

    endpoint: str = Field(min_length=1)
    price_per_request: float = Field(gt=0)
    currency: str = Field(min_length=1)
    description: str = ""

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_start_with_slash(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"endpoint must start with '/', got: {v!r}")
        return v


class AgentPassConfig(BaseModel):
    """agentpass.json のルートスキーマ。"""

    model_config = {"extra": "ignore"}

    agentpass_version: str
    merchant_id: str
    merchant_name: str = Field(min_length=1)
    public_key: str
    accepted_currencies: list[str] = Field(min_length=1)
    pricing: list[PricingEntry] = Field(min_length=1)
    settlement_address: str = Field(min_length=1)
    min_agent_credit_score: Annotated[float, Field(ge=0.0, le=1.0)]

    @field_validator("agentpass_version")
    @classmethod
    def version_must_be_supported(cls, v: str) -> str:
        if v not in SUPPORTED_VERSIONS:
            raise ValueError(
                f"Unsupported agentpass_version: {v!r}. "
                f"Supported: {sorted(SUPPORTED_VERSIONS)}"
            )
        return v

    @field_validator("merchant_id")
    @classmethod
    def merchant_id_must_be_uuid(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"merchant_id must be a valid UUID, got: {v!r}")
        return v

    @field_validator("public_key")
    @classmethod
    def public_key_must_be_valid_ed25519(cls, v: str) -> str:
        """base64url エンコードされた 32 バイトの Ed25519 公開鍵であることを確認する。"""
        try:
            # base64url はパディングなしが一般的なので補完して decode する
            padded = v + "=" * (-len(v) % 4)
            decoded = base64.urlsafe_b64decode(padded)
        except Exception as exc:
            raise ValueError(f"public_key is not valid base64url: {exc}") from exc

        if len(decoded) != _ED25519_PUBLIC_KEY_BYTES:
            raise ValueError(
                f"public_key must decode to {_ED25519_PUBLIC_KEY_BYTES} bytes "
                f"(Ed25519), got {len(decoded)} bytes"
            )
        return v


# ---------------------------------------------------------------------------
# HTTP 取得（差し替え可能）
# ---------------------------------------------------------------------------

def _default_fetch(url: str) -> bytes:
    """urllib を使って URL の内容を取得する。"""
    try:
        with urllib.request.urlopen(url, timeout=_DEFAULT_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise MerchantUnverifiedError(
            f"HTTP {exc.code} fetching agentpass.json from {url}"
        ) from exc
    except urllib.error.URLError as exc:
        raise MerchantUnverifiedError(
            f"Connection error fetching agentpass.json from {url}: {exc.reason}"
        ) from exc


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------

def fetch_agentpass_config(
    base_url: str,
    _fetch: Callable[[str], bytes] | None = None,
) -> AgentPassConfig:
    """
    加盟店ドメインから agentpass.json を取得し、検証済みの設定を返す。

    Args:
        base_url: 加盟店のベースURL（例: "https://merchant.example.com"）
        _fetch:   HTTP取得関数。None の場合は標準 urllib を使用（テスト用に差し替え可能）

    Returns:
        バリデーション済みの AgentPassConfig

    Raises:
        MerchantUnverifiedError: 取得失敗・JSON不正・スキーマ不一致のいずれかの場合
    """
    url = f"{base_url.rstrip('/')}/.well-known/agentpass.json"
    fetcher = _fetch if _fetch is not None else _default_fetch

    # 1. HTTP 取得
    try:
        raw = fetcher(url)
    except MerchantUnverifiedError:
        raise
    except Exception as exc:
        raise MerchantUnverifiedError(
            f"Unexpected error fetching {url}: {exc}"
        ) from exc

    # 2. JSON パース
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MerchantUnverifiedError(
            f"Invalid JSON in agentpass.json from {base_url}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise MerchantUnverifiedError(
            f"agentpass.json must be a JSON object, got {type(data).__name__}"
        )

    # 3. Pydantic スキーマ検証
    try:
        return AgentPassConfig.model_validate(data)
    except Exception as exc:
        raise MerchantUnverifiedError(
            f"agentpass.json schema validation failed for {base_url}: {exc}"
        ) from exc
