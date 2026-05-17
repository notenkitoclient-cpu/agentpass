"""
AgentPass Core — 非同期 agentpass.json クローラー

4層の防衛線を実装:
  1. SSRF防御    : DNS解決でプライベートIP/ループバックを即拒否
  2. 1MB制限     : ストリームチャンク読み込みで巨大レスポンスを即切断
  3. タイムアウト: 接続・読み取りとも 5 秒（デフォルト）
  4. TTLキャッシュ: ドメインごとに 3600 秒の O(1) インメモリキャッシュ
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from typing import Dict, List, Tuple

import httpx
from pydantic import BaseModel, Field, ValidationError


# ---------------------------------------------------------------------------
# Pydantic スキーマ
# ---------------------------------------------------------------------------

class PricingSchema(BaseModel):
    """加盟店が公開するエンドポイント単位の価格情報。"""

    model_config = {"extra": "ignore"}

    endpoint: str
    price_per_token: float = Field(..., ge=0.0)


class MerchantMetadata(BaseModel):
    """agentpass.json のルートスキーマ。"""

    model_config = {"extra": "ignore"}

    agentpass_version: str
    merchant_id: str
    public_key: str          # Ed25519 公開鍵の HEX 文字列（64 chars = 32 bytes）
    pricing: List[PricingSchema]


# ---------------------------------------------------------------------------
# クローラー
# ---------------------------------------------------------------------------

class AgentPassCrawler:
    """
    指定ドメインの agentpass.json を非同期で取得・検証・キャッシュするクローラー。

    使い方:
      crawler = AgentPassCrawler()
      metadata = await crawler.fetch_merchant_metadata("merchant.example.com")
      public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(metadata.public_key))
    """

    def __init__(
        self,
        timeout: float = 5.0,
        max_bytes: int = 1_048_576,
        ttl_seconds: int = 3600,
    ) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[float, MerchantMetadata]] = {}

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------

    async def fetch_merchant_metadata(
        self, domain: str, force_refresh: bool = False
    ) -> MerchantMetadata:
        """
        https://{domain}/.well-known/agentpass.json を取得・検証し返す。

        Args:
            domain:        スキームなしのドメイン名（例: "merchant.example.com"）
            force_refresh: True の場合キャッシュを無視して再取得する

        Returns:
            検証済みの MerchantMetadata

        Raises:
            ValueError:   SSRF検知 / 1MB超過 / JSON不正 / スキーマ不一致
            RuntimeError: HTTP 4xx/5xx / ネットワークエラー
        """
        # 【防衛線4】キャッシュチェック
        if not force_refresh and domain in self._cache:
            expiry, cached = self._cache[domain]
            if time.time() < expiry:
                return cached

        # 【防衛線1】SSRF防御
        if self._is_private_ip(domain):
            raise ValueError(
                f"SSRF Protection: domain {domain!r} resolves to a private/loopback "
                "IP address. Request blocked."
            )

        url = f"https://{domain}/.well-known/agentpass.json"
        content = await self._stream_with_limit(url)
        data = self._parse_json(url, content)
        metadata = self._validate_schema(url, data)

        # 【防衛線4】キャッシュ書き込み
        self._cache[domain] = (time.time() + self.ttl_seconds, metadata)
        return metadata

    # ------------------------------------------------------------------
    # 内部メソッド
    # ------------------------------------------------------------------

    def _is_private_ip(self, hostname: str) -> bool:
        """
        【防衛線1】ホスト名を DNS 解決し、プライベート/ループバック/リンクローカル
        アドレスが含まれていれば True を返す。解決失敗も危険と見なし True を返す。
        """
        try:
            _, _, ip_list = socket.gethostbyname_ex(hostname)
        except socket.gaierror:
            return True

        if not ip_list:
            return True

        for ip_str in ip_list:
            try:
                addr = ipaddress.ip_address(ip_str)
                if (
                    addr.is_private
                    or addr.is_loopback
                    or addr.is_link_local
                    or addr.is_reserved
                    or addr.is_multicast
                    or addr.is_unspecified
                ):
                    return True
            except ValueError:
                return True

        return False

    async def _stream_with_limit(self, url: str) -> bytes:
        """
        【防衛線2+3】ストリーミングで受信し、max_bytes 超で即切断する。
        HTTP 4xx/5xx は RuntimeError に変換する。
        """
        timeout_cfg = httpx.Timeout(self.timeout)
        try:
            async with httpx.AsyncClient(timeout=timeout_cfg) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code >= 400:
                        raise RuntimeError(
                            f"HTTP {response.status_code} error fetching {url}"
                        )
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise ValueError(
                                f"Security Boundary Exceeded: response from {url} "
                                f"exceeds {self.max_bytes} bytes. Connection aborted."
                            )
                        chunks.append(chunk)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise RuntimeError(f"Network error fetching {url}: {exc}") from exc

        return b"".join(chunks)

    @staticmethod
    def _parse_json(url: str, content: bytes) -> dict:
        """JSON パース。不正構造は即 ValueError に変換する。"""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON from {url}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"agentpass.json must be a JSON object, got "
                f"{type(data).__name__} from {url}"
            )
        return data

    @staticmethod
    def _validate_schema(url: str, data: dict) -> MerchantMetadata:
        """Pydantic v2 によるスキーマ厳格検証。"""
        try:
            return MerchantMetadata.model_validate(data)
        except ValidationError as exc:
            raise ValueError(
                f"Schema validation failed for {url}: {exc}"
            ) from exc
