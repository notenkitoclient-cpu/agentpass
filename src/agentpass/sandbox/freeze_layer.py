"""
EXP-006: Thin wrapper that adds burst-freeze enforcement around SandboxVerifier.

Responsibilities (bounded):
  - Check BurstFreezeDetector before delegating to inner verifier
  - Observe replay errors from inner verifier and record them to BurstFreezeDetector
  - Append spending_frozen audit record when freeze is triggered or active

Does NOT: modify SandboxVerifier, ReplayGuard, or any inner component.
"""

from __future__ import annotations

import uuid

from src.core.token_verifier import InvalidPayloadError, VerifiedClaims

from .audit_log import AuditLog
from .burst_freeze import BurstFreezeDetector
from .errors import SpendingFrozenError
from .verifier import SandboxVerifier

# Must match the message raised by SandboxVerifier for replay events.
_REPLAY_SIGNAL = "Replay attack detected"


class FreezeLayer:
    """
    Decorates a SandboxVerifier with replay-burst freeze enforcement.

    Flow:
      1. If frozen  → log spending_frozen, raise SpendingFrozenError (503)
      2. Delegate   → inner.verify(token)
      3. On replay  → record_replay(); if newly frozen, log spending_frozen
      4. On success → return VerifiedClaims unchanged

    The inner SandboxVerifier and ReplayGuard are not modified.
    """

    def __init__(
        self,
        inner: SandboxVerifier,
        burst: BurstFreezeDetector,
        audit_log: AuditLog,
    ) -> None:
        self._inner = inner
        self._burst = burst
        self._audit_log = audit_log

    def verify(self, token: str) -> VerifiedClaims:
        """
        Verify a token with burst-freeze enforcement.

        Raises:
            SpendingFrozenError   — spending is currently frozen (HTTP 503)
            InvalidPayloadError   — replayed or invalid token (propagated from inner)
            TokenExpiredError     — token expired (propagated from inner)
            SandboxBudgetExceededError — budget exceeded (propagated from inner)
        """
        if self._burst.is_frozen():
            self._append_frozen_record()
            burst_count = self._burst.replay_count_in_window()
            raise SpendingFrozenError(
                "Spending temporarily frozen due to replay burst",
                burst_count=burst_count,
            )

        try:
            return self._inner.verify(token)
        except InvalidPayloadError as exc:
            if _REPLAY_SIGNAL in str(exc):
                just_frozen = self._burst.record_replay()
                if just_frozen:
                    self._append_frozen_record()
            raise

    # ------------------------------------------------------------------

    def _append_frozen_record(self) -> None:
        record = self._audit_log.make_spending_frozen_record(
            burst_count=self._burst.replay_count_in_window(),
            nonce=str(uuid.uuid4()),
        )
        self._audit_log.append(record)
