"""
EXP-005c: Agent-scoped JWT signer.

SandboxSigner owns a single agent's private key and produces JWTs that
include the key_id in the standard JWT kid header field. The kid allows
AgentKeyRegistry to resolve the correct public key at verification time.

Responsibilities (bounded):
  - Sign TokenRequest payloads on behalf of one specific agent
  - Embed kid in the JWT header for verifier-side key lookup

Does NOT: manage key storage, interact with registry, or log audit events.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.core.token_issuer import TokenRequest


class SandboxSigner:
    """
    JWT signer for a single agent identity.

    Produces tokens compatible with verify_token() but with an additional
    ``kid`` header field so multi-agent verifiers can resolve the right key.

    Args:
        agent_id:    The agent this signer is authorised to sign for.
        key_id:      Unique identifier for this keypair in AgentKeyRegistry.
        private_key: Ed25519 private key for signing.

    Usage:
        signer = SandboxSigner("agent-a", "key-a-001", private_key_a)
        token = signer.sign(req)  # req.agent_id must equal "agent-a"
    """

    def __init__(
        self,
        agent_id: str,
        key_id: str,
        private_key: Ed25519PrivateKey,
    ) -> None:
        self._agent_id = agent_id
        self._key_id = key_id
        self._private_key = private_key

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign(self, req: TokenRequest) -> str:
        """
        Sign a TokenRequest and return a JWT string.

        The JWT header contains ``kid=self.key_id`` so the receiving
        SandboxVerifier can resolve the correct public key via AgentKeyRegistry.

        Raises:
            ValueError — req.agent_id does not match self.agent_id
        """
        if req.agent_id != self._agent_id:
            raise ValueError(
                f"req.agent_id={req.agent_id!r} does not match "
                f"signer.agent_id={self._agent_id!r}"
            )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=req.expires_in_seconds)

        payload = {
            "sub": req.agent_id,
            "aud": req.destination_url,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": str(uuid.uuid4()),
            "amt": req.amount_requested,
            "cur": "JPY",
            "agp": "1",
        }

        return jwt.encode(
            payload,
            self._private_key,
            algorithm="EdDSA",
            headers={"kid": self._key_id},
        )
