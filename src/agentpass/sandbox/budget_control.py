"""
EXP-005a: Single-transaction budget guard for sandbox experiments.

Intentionally simpler than core.CircuitBreaker (sliding window):
  - No time window — checks each transaction in isolation
  - No state mutation on rejection (idempotent, replayable)
  - Raises SandboxBudgetExceededError (HTTP 402) when amount > budget_limit
"""

from __future__ import annotations

from .errors import SandboxBudgetExceededError


class SandboxBudgetControl:
    """
    Per-transaction budget gate.

    Usage:
        ctrl = SandboxBudgetControl(budget_limit=0.01)
        ctrl.check(amount=0.001)   # passes
        ctrl.check(amount=0.02)    # raises SandboxBudgetExceededError

    Rejection is idempotent — calling check() with an over-limit amount
    never changes internal state, making rejections fully replayable from
    the audit log.
    """

    def __init__(self, budget_limit: float) -> None:
        if budget_limit <= 0:
            raise ValueError(f"budget_limit must be positive, got {budget_limit}")
        self._limit = budget_limit

    @property
    def budget_limit(self) -> float:
        return self._limit

    def check(self, amount: float) -> None:
        """
        Raise SandboxBudgetExceededError if amount > budget_limit.
        No state is modified on either success or failure.
        """
        if amount > self._limit:
            raise SandboxBudgetExceededError(
                f"Purchase amount {amount} JPY exceeds budget limit {self._limit} JPY",
                amount=amount,
                budget_limit=self._limit,
            )
