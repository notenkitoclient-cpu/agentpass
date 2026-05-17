"""
AgentPass Core — JWTトークン検証モジュール

ai-instructions.md セクション7 のエラーコード体系に準拠。
署名・有効期限・宛先URLの3段階を順番に検証する。
"""

from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# AgentPassトークンに必須のカスタムクレーム
_REQUIRED_CLAIMS = ("amt", "cur", "agp", "jti")


# ---------------------------------------------------------------------------
# 例外クラス（ai-instructions.md セクション7 に対応）
# ---------------------------------------------------------------------------

class VerificationError(Exception):
    """トークン検証失敗の基底例外。http_status と error_code を持つ。"""
    http_status: int
    error_code: str


class InvalidPayloadError(VerificationError):
    """400 INVALID_PAYLOAD — 署名不正・改ざん・形式エラー・必須クレーム欠落"""
    http_status = 400
    error_code = "INVALID_PAYLOAD"


class TokenExpiredError(VerificationError):
    """401 TOKEN_EXPIRED — トークンの有効期限切れ"""
    http_status = 401
    error_code = "TOKEN_EXPIRED"


class DestinationMismatchError(VerificationError):
    """403 DESTINATION_MISMATCH — aud クレームと加盟店URLが不一致"""
    http_status = 403
    error_code = "DESTINATION_MISMATCH"


# ---------------------------------------------------------------------------
# 検証済みクレームの返却型
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerifiedClaims:
    agent_id: str        # sub
    destination_url: str # aud
    amount: float        # amt (JPY)
    currency: str        # cur
    token_id: str        # jti（リプレイ防止ID）
    issued_at: int       # iat（unix timestamp）
    expires_at: int      # exp（unix timestamp）


# ---------------------------------------------------------------------------
# 検証関数
# ---------------------------------------------------------------------------

def verify_token(
    token: str,
    public_key: Ed25519PublicKey,
    merchant_url: str,
) -> VerifiedClaims:
    """
    AgentPassトークンを3段階で検証し、検証済みクレームを返す。

    検証順序:
      1. 署名・形式（失敗 → InvalidPayloadError 400）
      2. 有効期限（失敗 → TokenExpiredError 401）
      3. 宛先URL一致（失敗 → DestinationMismatchError 403）

    PyJWTは署名→exp→audの順に検証するため、
    この順序は自動的に保証される。
    """
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["EdDSA"],
            audience=merchant_url,
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise DestinationMismatchError(
            f"Token audience does not match merchant URL: {merchant_url}"
        ) from exc
    except jwt.PyJWTError as exc:
        # DecodeError, InvalidSignatureError, MissingRequiredClaimError 等
        raise InvalidPayloadError(f"Token verification failed: {exc}") from exc

    # AgentPass固有クレームの存在確認（JWTとしては正しくてもAPP層で弾く）
    missing = [c for c in _REQUIRED_CLAIMS if c not in claims]
    if missing:
        raise InvalidPayloadError(f"Missing required AgentPass claims: {missing}")

    return VerifiedClaims(
        agent_id=claims["sub"],
        destination_url=claims["aud"],
        amount=claims["amt"],
        currency=claims["cur"],
        token_id=claims["jti"],
        issued_at=claims["iat"],
        expires_at=claims["exp"],
    )
