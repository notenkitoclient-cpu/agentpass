"""
AgentPass Merchant — Authorization ミドルウェア

Starlette/FastAPI の BaseHTTPMiddleware を継承した ASGI ミドルウェア。
"Authorization: AgentPass <token>" ヘッダーを厳格に検証し、
失敗時は AI が自律判定しやすいエラーコード付き JSON を早期返却する。

検証の流れ:
  1. Authorization ヘッダーの存在チェック
  2. "AgentPass " スキームチェック
  3. トークン空文字チェック
  4. Week 1 資産（token_verifier）による署名・期限・宛先の3段階検証
       - 署名不正 / 改ざん → 400 INVALID_PAYLOAD
       - 期限切れ           → 401 TOKEN_EXPIRED
       - 宛先 URL 不一致   → 403 DESTINATION_MISMATCH
"""

from __future__ import annotations

import base64
from collections.abc import Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from core.token_verifier import VerificationError, verify_token
from merchant.agentpass_crawler import AgentPassConfig, fetch_agentpass_config

_SCHEME = "AgentPass"
_PREFIX = f"{_SCHEME} "


class AgentPassMiddleware(BaseHTTPMiddleware):
    """
    Authorization: AgentPass <token> を検証する ASGI ミドルウェア。

    典型的な初期化パターン（3種類）:

      # 1. 公開鍵を直接渡す（最もシンプル）
      app.add_middleware(AgentPassMiddleware, public_key=ed25519_public_key)

      # 2. AgentPassConfig から初期化（クローラーで取得した設定から）
      config = fetch_agentpass_config("https://agentpass.example.com")
      middleware = AgentPassMiddleware.from_agentpass_config(app, config)

      # 3. AgentPass の URL から公開鍵を自律取得
      middleware = AgentPassMiddleware.from_agentpass_url(
          app, "https://agentpass.example.com"
      )
    """

    def __init__(self, app: ASGIApp, *, public_key: Ed25519PublicKey) -> None:
        super().__init__(app)
        self._public_key = public_key

    # ------------------------------------------------------------------
    # 代替コンストラクタ（自律取得パターン）
    # ------------------------------------------------------------------

    @classmethod
    def from_agentpass_config(
        cls, app: ASGIApp, config: AgentPassConfig
    ) -> AgentPassMiddleware:
        """AgentPassConfig の public_key フィールドから公開鍵を復元して初期化する。"""
        return cls(app, public_key=_load_public_key(config.public_key))

    @classmethod
    def from_agentpass_url(
        cls,
        app: ASGIApp,
        agentpass_base_url: str,
        _fetch: Callable[[str], bytes] | None = None,
    ) -> AgentPassMiddleware:
        """
        AgentPass サービスの agentpass.json から公開鍵を自律取得して初期化する。

        _fetch を注入することでテスト時の外部通信をゼロにできる。
        """
        config = fetch_agentpass_config(agentpass_base_url, _fetch)
        return cls.from_agentpass_config(app, config)

    # ------------------------------------------------------------------
    # リクエスト処理
    # ------------------------------------------------------------------

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")

        if not auth:
            return _err(400, "INVALID_PAYLOAD", "Missing Authorization header")

        if not auth.startswith(_PREFIX):
            scheme = auth.split(" ", 1)[0]
            return _err(
                400,
                "INVALID_PAYLOAD",
                f"Invalid Authorization scheme: {scheme!r}. Expected: {_SCHEME!r}",
            )

        token = auth[len(_PREFIX):]
        if not token.strip():
            return _err(400, "INVALID_PAYLOAD", "Empty token in Authorization header")

        # str(request.url) = 完全な URL（スキーム・ホスト・パス・クエリを含む）
        # トークンの aud クレームと完全一致させることで宛先を固定する
        merchant_url = str(request.url)

        try:
            verify_token(token, self._public_key, merchant_url)
        except VerificationError as exc:
            return _err(exc.http_status, exc.error_code, str(exc))

        return await call_next(request)


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------

def _load_public_key(b64url: str) -> Ed25519PublicKey:
    """base64url エンコードされた Ed25519 公開鍵をオブジェクトに復元する。"""
    padded = b64url + "=" * (-len(b64url) % 4)
    raw = base64.urlsafe_b64decode(padded)
    return Ed25519PublicKey.from_public_bytes(raw)


def _err(status: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error_code": error_code, "message": message, "http_status": status},
        status_code=status,
    )
