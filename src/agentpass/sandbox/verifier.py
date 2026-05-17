"""
EXP-005a/b: Token verification pipeline with budget control and replay guard.

Pipeline:
  1. verify_token()        — signature, expiry, audience (InvalidPayloadError / TokenExpiredError)
  2. validate claims       — included in verify_token()
  3. replay pre-check      — ReplayGuard (atomic, EXP-005b) or AnomalyDetector fallback
  4. budget check          — SandboxBudgetControl.check()
  5. reject if exceeded    — append audit log, raise SandboxBudgetExceededError
  6. return VerifiedClaims — if replay_guard provided, also logs purchase_approved
"""

from __future__ import annotations

import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.core.anomaly_detector import AnomalyDetector
from src.core.token_verifier import InvalidPayloadError, VerifiedClaims, verify_token

from .audit_log import AuditLog
from .budget_control import SandboxBudgetControl
from .errors import SandboxBudgetExceededError
from .replay_guard import ReplayGuard


class SandboxVerifier:
    """
    Token verifier for EXP-005a/b sandbox experiments.

    Wraps the core verify_token() pipeline with:
      - Replay detection via ReplayGuard (atomic) or AnomalyDetector (fallback)
      - Per-transaction budget gate via SandboxBudgetControl
      - Audit logging of budget_exceeded, replay_detected, and purchase_approved events

    Usage:
        verifier = SandboxVerifier(public_key, merchant_url, budget_control, audit_log)
        try:
            claims = verifier.verify(token)
        except SandboxBudgetExceededError as exc:
            return Response(exc.to_response(), status=402)
        except VerificationError as exc:
            return Response({"error": str(exc)}, status=exc.http_status)
    """

    def __init__(
        self,
        public_key: Ed25519PublicKey,
        merchant_url: str,
        budget_control: SandboxBudgetControl,
        audit_log: AuditLog,
        detector: AnomalyDetector | None = None,
        replay_guard: ReplayGuard | None = None,
    ) -> None:
        self._public_key = public_key
        self._merchant_url = merchant_url
        self._budget_control = budget_control
        self._audit_log = audit_log
        self._detector = detector if detector is not None else AnomalyDetector()
        self._replay_guard = replay_guard

    def verify(self, token: str) -> VerifiedClaims:
        """
        Run the pipeline. Returns VerifiedClaims on success.

        Raises:
            InvalidPayloadError  — bad signature, missing claims, or replay detected
            TokenExpiredError    — token past expiry
            DestinationMismatchError — aud ≠ merchant_url
            SandboxBudgetExceededError — amount > budget_limit; audit logged
        """
        nonce = str(uuid.uuid4())

        # Steps 1–2: signature, expiry, audience, required AgentPass claims
        claims = verify_token(token, self._public_key, self._merchant_url)

        # Step 3: replay check
        if self._replay_guard is not None:
            # Atomic check-and-register: only one concurrent caller gets True
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

        # Step 6: log purchase_approved (when replay_guard is active) and return
        if self._replay_guard is not None:
            record = self._audit_log.make_purchase_approved_record(
                agent_id=claims.agent_id,
                amount=claims.amount,
                token_id=claims.token_id,
                nonce=nonce,
            )
            self._audit_log.append(record)

        return claims
