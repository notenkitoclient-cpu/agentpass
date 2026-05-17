"""
AgentPass Core — 使い捨てJWTトークン発行モジュール

ai-instructions.md セクション2 のスキーマに完全準拠。
トークンは1回限り有効。再利用はリプレイ攻撃として扱われる。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

if TYPE_CHECKING:
    from core.circuit_breaker import CircuitBreaker, CircuitBreakerStatus


@dataclass(frozen=True)
class TokenRequest:
    agent_id: str
    destination_url: str
    amount_requested: float    # JPY
    purpose: str
    expires_in_seconds: int = 60

    def __post_init__(self):
        if not self.destination_url.startswith("https://"):
            raise ValueError("destination_url must use HTTPS")
        if self.amount_requested <= 0:
            raise ValueError("amount_requested must be positive")
        if not (1 <= self.expires_in_seconds <= 300):
            raise ValueError("expires_in_seconds must be between 1 and 300")
        if len(self.purpose) > 128:
            raise ValueError("purpose must be 128 characters or less")


@dataclass(frozen=True)
class IssuedToken:
    token: str
    token_id: str
    valid_until: datetime
    destination_url: str
    max_amount: float
    agent_id: str
    circuit_breaker: CircuitBreakerStatus | None = field(default=None)


def issue_token(
    request: TokenRequest,
    private_key: Ed25519PrivateKey,
    circuit_breaker: CircuitBreaker | None = None,
) -> IssuedToken:
    """
    Ed25519署名付き使い捨てJWTを発行する。

    JWTペイロードはai-instructions.md セクション2.3に準拠:
      sub, aud, iat, exp, jti, amt, cur, agp

    circuit_breaker が指定された場合、発行前に制限チェックと使用量記録を行う。
    制限超過時は BudgetExceededError / RateLimitedError を送出し、トークンは発行しない。
    """
    cb_status = None
    if circuit_breaker is not None:
        cb_status = circuit_breaker.check_and_record(
            request.agent_id, request.amount_requested
        )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=request.expires_in_seconds)
    token_id = str(uuid.uuid4())

    payload = {
        "sub": request.agent_id,
        "aud": request.destination_url,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": token_id,
        "amt": request.amount_requested,
        "cur": "JPY",
        "agp": "1",
    }

    token = jwt.encode(payload, private_key, algorithm="EdDSA")

    return IssuedToken(
        token=token,
        token_id=token_id,
        valid_until=expires_at,
        destination_url=request.destination_url,
        max_amount=request.amount_requested,
        agent_id=request.agent_id,
        circuit_breaker=cb_status,
    )


def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """開発・テスト用のEd25519鍵ペアを生成する。"""
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()
