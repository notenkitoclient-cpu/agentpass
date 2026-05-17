"""
EXP-005a: Sandbox-specific exceptions.

SandboxBudgetExceededError is distinct from core.BudgetExceededError:
  - core uses HTTP 429 (rate-limiting semantics)
  - sandbox uses HTTP 402 (payment-required semantics — more precise for budget gates)
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
