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


# ---------------------------------------------------------------------------
# EXP-005c: Multi-agent keypair isolation errors
# ---------------------------------------------------------------------------

class SignerMismatchError(Exception):
    """
    Token sub (agent_id) does not match the owner of the signing key (EXP-005c).

    HTTP 403 — the token is cryptographically valid but the claimed identity
    does not match the registered key owner.
    """

    http_status: int = 403
    error_code: str = "SIGNER_MISMATCH"

    def __init__(
        self,
        message: str,
        *,
        key_id: str,
        claimed_agent_id: str,
        key_owner_agent_id: str,
    ) -> None:
        super().__init__(message)
        self.key_id = key_id
        self.claimed_agent_id = claimed_agent_id
        self.key_owner_agent_id = key_owner_agent_id


class CompromisedKeyError(Exception):
    """
    The signing key has been marked compromised (EXP-005c).

    HTTP 403 — token is structurally valid but the key is no longer trusted.
    """

    http_status: int = 403
    error_code: str = "SIGNER_COMPROMISED"

    def __init__(self, message: str, *, key_id: str) -> None:
        super().__init__(message)
        self.key_id = key_id


class UnknownKeyIdError(Exception):
    """
    The kid in the token header is not registered in AgentKeyRegistry (EXP-005c).

    HTTP 401 — key is unrecognized; cannot verify signer identity.
    """

    http_status: int = 401
    error_code: str = "UNKNOWN_KEY_ID"

    def __init__(self, message: str, *, key_id: str) -> None:
        super().__init__(message)
        self.key_id = key_id


class UnknownAgentIdError(Exception):
    """
    The agent_id is not registered in AgentKeyRegistry (EXP-005c).

    HTTP 401 — agent identity is unrecognized.
    """

    http_status: int = 401
    error_code: str = "UNKNOWN_AGENT_ID"
