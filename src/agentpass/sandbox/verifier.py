"""
EXP-005a/b/c: Token verification pipeline with budget control, replay guard,
and multi-agent key resolution.

Pipeline:
  0. key resolution   — (EXP-005c) decode kid → resolve public key from AgentKeyRegistry
  1. verify_token()   — signature, expiry, audience (InvalidPayloadError / TokenExpiredError)
  2. validate claims  — included in verify_token()
  2b. signer check    — (EXP-005c) confirm sub matches key owner; log signer_rejected/verified
  3. replay pre-check — ReplayGuard (atomic, EXP-005b) or AnomalyDetector fallback
  4. budget check     — SandboxBudgetControl.check()
  5. reject if exceeded — append audit log, raise SandboxBudgetExceededError
  6. return VerifiedClaims — if replay_guard/key_registry active, also logs purchase_approved
"""

from __future__ import annotations

import uuid

import jwt as _pyjwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.core.anomaly_detector import AnomalyDetector
from src.core.token_verifier import InvalidPayloadError, VerifiedClaims, verify_token

from .agent_key_registry import AgentKeyRegistry
from .audit_log import AuditLog
from .budget_control import SandboxBudgetControl
from .errors import CompromisedKeyError, SandboxBudgetExceededError, SignerMismatchError, UnknownKeyIdError
from .replay_guard import ReplayGuard


def _extract_kid(token: str) -> str | None:
    """Return the kid header field from a JWT without verifying the signature."""
    try:
        header = _pyjwt.get_unverified_header(token)
        return header.get("kid")
    except _pyjwt.exceptions.PyJWTError:
        return None


class SandboxVerifier:
    """
    Token verifier for EXP-005a/b/c sandbox experiments.

    Wraps the core verify_token() pipeline with:
      - (EXP-005c) Multi-agent key resolution via AgentKeyRegistry
      - Replay detection via ReplayGuard (atomic) or AnomalyDetector (fallback)
      - Per-transaction budget gate via SandboxBudgetControl
      - Audit logging of all rejection and approval events

    Usage (single-agent, EXP-005a/b):
        verifier = SandboxVerifier(public_key, merchant_url, budget_control, audit_log)

    Usage (multi-agent, EXP-005c):
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a-001", agent_a_pubkey)
        verifier = SandboxVerifier(
            public_key=None,   # ignored when key_registry is provided
            merchant_url=..., budget_control=..., audit_log=...,
            key_registry=registry,
        )
    """

    def __init__(
        self,
        public_key: Ed25519PublicKey | None,
        merchant_url: str,
        budget_control: SandboxBudgetControl,
        audit_log: AuditLog,
        detector: AnomalyDetector | None = None,
        replay_guard: ReplayGuard | None = None,
        key_registry: AgentKeyRegistry | None = None,
    ) -> None:
        if public_key is None and key_registry is None:
            raise ValueError("Either public_key or key_registry must be provided")
        self._public_key = public_key
        self._merchant_url = merchant_url
        self._budget_control = budget_control
        self._audit_log = audit_log
        self._detector = detector if detector is not None else AnomalyDetector()
        self._replay_guard = replay_guard
        self._key_registry = key_registry

    def verify(self, token: str) -> VerifiedClaims:
        """
        Run the pipeline. Returns VerifiedClaims on success.

        Raises:
            InvalidPayloadError       — bad signature, missing claims, or replay detected
            TokenExpiredError         — token past expiry
            DestinationMismatchError  — aud ≠ merchant_url
            CompromisedKeyError       — (EXP-005c) signing key is compromised
            UnknownKeyIdError         — (EXP-005c) kid not in registry
            SignerMismatchError       — (EXP-005c) sub ≠ key owner
            SandboxBudgetExceededError — amount > budget_limit; audit logged
        """
        nonce = str(uuid.uuid4())

        # Step 0: multi-agent key resolution
        if self._key_registry is not None:
            kid = _extract_kid(token)
            if kid is None:
                raise InvalidPayloadError("Missing kid in token header")
            try:
                owner_agent_id, effective_key = self._key_registry.resolve(kid)
            except (CompromisedKeyError, UnknownKeyIdError) as exc:
                record = self._audit_log.make_signer_rejected_record(
                    key_id=kid,
                    reason=exc.error_code.lower(),
                    nonce=nonce,
                    signer_status="compromised" if isinstance(exc, CompromisedKeyError) else "unknown",
                )
                self._audit_log.append(record)
                raise
        else:
            kid = None
            owner_agent_id = None
            effective_key = self._public_key

        # Steps 1–2: signature, expiry, audience, required AgentPass claims
        claims = verify_token(token, effective_key, self._merchant_url)

        # Step 2b: signer identity check (multi-agent mode)
        if owner_agent_id is not None and claims.agent_id != owner_agent_id:
            record = self._audit_log.make_signer_rejected_record(
                key_id=kid,
                reason="signer_mismatch",
                nonce=nonce,
                signer_status="active",
                signature_verified=True,
                agent_id=claims.agent_id,
                jti=claims.token_id,
            )
            self._audit_log.append(record)
            raise SignerMismatchError(
                f"sub={claims.agent_id!r} does not match key owner {owner_agent_id!r}",
                key_id=kid,
                claimed_agent_id=claims.agent_id,
                key_owner_agent_id=owner_agent_id,
            )

        # Step 3: replay check
        if self._replay_guard is not None:
            if not self._replay_guard.check_and_register(claims.token_id):
                record = self._audit_log.make_replay_detected_record(
                    agent_id=claims.agent_id,
                    token_id=claims.token_id,
                    nonce=nonce,
                )
                self._audit_log.append(record)
                raise InvalidPayloadError("Replay attack detected: token already used")
        elif self._detector.is_replay_attack(claims.token_id, claims.expires_at):
            raise InvalidPayloadError("Replay attack detected: token already used")

        # Steps 4–5: budget gate — reject and log if exceeded
        try:
            self._budget_control.check(claims.amount)
        except SandboxBudgetExceededError as exc:
            record = self._audit_log.make_budget_exceeded_record(
                agent_id=claims.agent_id,
                amount=claims.amount,
                budget_limit=exc.budget_limit,
                nonce=nonce,
            )
            self._audit_log.append(record)
            raise

        # Step 6: success audit logging
        if self._key_registry is not None:
            record = self._audit_log.make_signer_verified_record(
                agent_id=claims.agent_id,
                key_id=kid,
                jti=claims.token_id,
                nonce=nonce,
            )
            self._audit_log.append(record)

        if self._replay_guard is not None:
            record = self._audit_log.make_purchase_approved_record(
                agent_id=claims.agent_id,
                amount=claims.amount,
                token_id=claims.token_id,
                nonce=nonce,
            )
            self._audit_log.append(record)

        return claims
