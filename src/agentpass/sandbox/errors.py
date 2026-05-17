"""
EXP-005a/006: Sandbox-specific exceptions.

SandboxBudgetExceededError is distinct from core.BudgetExceededError:
  - core uses HTTP 429 (rate-limiting semantics)
  - sandbox uses HTTP 402 (payment-required semantics — more precise for budget gates)

SpendingFrozenError (EXP-006): temporary freeze due to replay burst.
  - HTTP 503 Service Unavailable — not a permanent rejection
"""

from __future__ import annotations


class SandboxBudgetExceededError(Exception):
    """
    Raised when a purchase amount exceeds the configured budget limit.

    http_status = 402 Payment Required
    Budget state is NOT mutated on rejection — the check is idempotent.
    """

    http_status: int = 402
    error_code: str = "BUDGET_EXCEEDED"

    def __init__(self, message: str, *, amount: float, budget_limit: float) -> None:
        super().__init__(message)
        self.amount = amount
        self.budget_limit = budget_limit

    def to_response(self) -> dict:
        """Return the canonical rejection body for HTTP 402 responses."""
        return {
            "status": "rejected",
            "reason": "budget_exceeded",
            "error": "BudgetExceededError",
        }


class SpendingFrozenError(Exception):
    """
    Raised when spending is temporarily frozen due to a replay burst (EXP-006).

    http_status = 503 Service Unavailable — the freeze is temporary, not permanent.
    """

    http_status: int = 503
    error_code: str = "SPENDING_FROZEN"

    def __init__(self, message: str, *, burst_count: int) -> None:
        super().__init__(message)
        self.burst_count = burst_count

    def to_response(self) -> dict:
        return {
            "status": "frozen",
            "reason": "replay_burst_detected",
            "burst_count": self.burst_count,
            "error": "SpendingFrozenError",
        }
