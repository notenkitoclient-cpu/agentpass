"""
AgentPass Core — Authorization ミドルウェア（非同期・iss クレーム対応版）

BaseHTTPMiddleware を継承した ASGI ミドルウェア。
トークンの iss クレームから公開鍵を自律取得し、署名・宛先・期限を検証する。

処理フロー:
  1. Authorization ヘッダーの存在チェック（なければ 401）
  2. "AgentPass " スキームチェック（違えば 401）
  3. 署名検証なしで JWT デコードし、iss クレームを抽出（なければ 400）
  4. AgentPassCrawler で iss ドメインの公開鍵を非同期取得
  5. 取得した公開鍵で TokenVerifier を呼び出す（aud = str(request.url)）
  6. 成功時に request.state.agent_claims にクレームをバインド
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

import jwt as _jwt

from core.agentpass_crawler import AgentPassCrawler
from core.anomaly_detector import AnomalyDetector
from core.token_verifier import VerificationError, verify_token

_SCHEME = "AgentPass"
_PREFIX = f"{_SCHEME} "


class AuthorizationMiddleware(BaseHTTPMiddleware):
    """
    Authorization: AgentPass <token> を検証する非同期 ASGI ミドルウェア。

    公開鍵はトークンの iss クレームで指定されたドメインから自律取得する。
    検証成功後、デコード済みクレームを request.state.agent_claims にバインドする。

    初期化:
      # デフォルト設定で使用
      app.add_middleware(AuthorizationMiddleware)

      # テスト用にクローラー・検知器を注入
      app.add_middleware(AuthorizationMiddleware, crawler=mock_crawler, anomaly_detector=detector)
    """

    def __init__(
        self,
        app: ASGIApp,
        crawler: AgentPassCrawler | None = None,
        anomaly_detector: AnomalyDetector | None = None,
    ) -> None:
        super().__init__(app)
        self._crawler = crawler or AgentPassCrawler()
        self._anomaly_detector = anomaly_detector

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")

        # 1. ヘッダー存在チェック
        if not auth:
            return _err(401, "INVALID_PAYLOAD", "Missing Authorization header")

        # 2. スキームチェック
        if not auth.startswith(_PREFIX):
            scheme = auth.split(" ", 1)[0]
            return _err(
                401,
                "INVALID_PAYLOAD",
                f"Invalid Authorization scheme: {scheme!r}. Expected: {_SCHEME!r}",
            )

        token = auth[len(_PREFIX):].strip()
        if not token:
            return _err(401, "INVALID_PAYLOAD", "Empty token in Authorization header")

        # 3. 署名検証なしでデコードして iss クレームを抽出
        try:
            unverified = _jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_aud": False,
                },
            )
        except _jwt.PyJWTError as exc:
            return _err(400, "INVALID_PAYLOAD", f"Malformed JWT: {exc}")

        iss = unverified.get("iss")
        if not iss:
            return _err(400, "INVALID_PAYLOAD", "Missing 'iss' claim in token")

        # 4. iss ドメインから公開鍵を非同期取得
        try:
            metadata = await self._crawler.fetch_merchant_metadata(iss)
        except Exception as exc:
            return _err(503, "MERCHANT_UNVERIFIED", f"Failed to fetch metadata for {iss!r}: {exc}")

        # 5. TokenVerifier で署名・期限・宛先を検証
        #    aud = str(request.url)（完全 URL でトークンの宛先を固定）
        public_key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(metadata.public_key)
        )
        merchant_url = str(request.url)

        try:
            claims = verify_token(token, public_key, merchant_url)
        except VerificationError as exc:
            return _err(exc.http_status, exc.error_code, str(exc))

        # 6. リプレイ攻撃チェック（AnomalyDetector が注入されている場合のみ）
        if self._anomaly_detector is not None:
            if self._anomaly_detector.is_replay_attack(claims.token_id, float(claims.expires_at)):
                return _err(403, "REPLAY_ATTACK", f"Token {claims.token_id!r} has already been used")

        # 7. 検証成功 → クレームを下流エンドポイントへバインド
        request.state.agent_claims = claims
        return await call_next(request)


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------

def _err(status: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error_code": error_code, "message": message, "http_status": status},
        status_code=status,
    )
