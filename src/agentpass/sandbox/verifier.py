"""
EXP-005a: 6-step token verification pipeline with budget control.

Pipeline:
  1. verify_token()        — signature, expiry, audience (InvalidPayloadError / TokenExpiredError)
  2. validate claims       — included in verify_token()
  3. replay pre-check      — AnomalyDetector.is_replay_attack()
  4. budget check          — SandboxBudgetControl.check()
  5. reject if exceeded    — append audit log, raise SandboxBudgetExceededError
  6. return VerifiedClaims — caller is responsible for logging successful purchases
"""

from __future__ import annotations

import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.anomaly_detector import AnomalyDetector
from core.token_verifier import InvalidPayloadError, VerifiedClaims, verify_token

from .audit_log import AuditLog
from .budget_control import SandboxBudgetControl
from .errors import SandboxBudgetExceededError


class SandboxVerifier:
    """
    Token verifier for EXP-005a sandbox experiments.

    Wraps the core verify_token() pipeline with:
      - Replay detection via AnomalyDetector
      - Per-transaction budget gate via SandboxBudgetControl
      - Audit logging of budget_exceeded events

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
    ) -> None:
        self._public_key = public_key
        self._merchant_url = merchant_url
        self._budget_control = budget_control
        self._audit_log = audit_log
        self._detector = detector if detector is not None else AnomalyDetector()

    def verify(self, token: str) -> VerifiedClaims:
        """
        Run the 6-step pipeline. Returns VerifiedClaims on success.

        Raises:
            InvalidPayloadError  (step 1/3) — bad signature, missing claims, or replay
            TokenExpiredError    (step 1)   — token past expiry
            DestinationMismatchError (step 1) — aud ≠ merchant_url
            SandboxBudgetExceededError (step 4/5) — amount > budget_limit; audit logged
        """
        nonce = str(uuid.uuid4())

        # Steps 1–2: signature, expiry, audience, required AgentPass claims
        claims = verify_token(token, self._public_key, self._merchant_url)

        # Step 3: replay pre-check
        if self._detector.is_replay_attack(claims.token_id, claims.expires_at):
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

        # Step 6: return verified claims (success logging is caller's responsibility)
        return claims
