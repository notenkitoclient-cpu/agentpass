"""
EXP-005a: budget_exceeded → HTTP 402 の検証

3層:
  Layer 1 — SandboxBudgetExceededError の属性（http_status / error_code / to_response）
  Layer 2 — SandboxBudgetControl の境界値と冪等性
  Layer 3 — SandboxVerifier 統合（token → budget check → 402 + audit log）
"""

from __future__ import annotations

import pytest

from agentpass.sandbox.audit_log import AuditLog
from agentpass.sandbox.budget_control import SandboxBudgetControl
from agentpass.sandbox.errors import SandboxBudgetExceededError
from agentpass.sandbox.verifier import SandboxVerifier
from core.token_issuer import TokenRequest, generate_keypair, issue_token


# ---------------------------------------------------------------------------
# Layer 1 — SandboxBudgetExceededError の属性
# ---------------------------------------------------------------------------

class TestSandboxBudgetExceededErrorAttributes:
    def test_http_status_is_402(self):
        assert SandboxBudgetExceededError.http_status == 402

    def test_error_code(self):
        assert SandboxBudgetExceededError.error_code == "BUDGET_EXCEEDED"

    def test_to_response_status_field(self):
        exc = SandboxBudgetExceededError("msg", amount=0.002, budget_limit=0.001)
        assert exc.to_response()["status"] == "rejected"

    def test_to_response_reason_field(self):
        exc = SandboxBudgetExceededError("msg", amount=0.002, budget_limit=0.001)
        assert exc.to_response()["reason"] == "budget_exceeded"

    def test_to_response_error_field(self):
        exc = SandboxBudgetExceededError("msg", amount=0.002, budget_limit=0.001)
        assert exc.to_response()["error"] == "BudgetExceededError"

    def test_amount_and_budget_limit_stored(self):
        exc = SandboxBudgetExceededError("msg", amount=5.0, budget_limit=1.0)
        assert exc.amount == 5.0
        assert exc.budget_limit == 1.0

    def test_is_exception_subclass(self):
        assert issubclass(SandboxBudgetExceededError, Exception)


# ---------------------------------------------------------------------------
# Layer 2 — SandboxBudgetControl の境界値と冪等性
# ---------------------------------------------------------------------------

class TestSandboxBudgetControl:
    def test_amount_over_limit_raises(self):
        ctrl = SandboxBudgetControl(budget_limit=0.001)
        with pytest.raises(SandboxBudgetExceededError):
            ctrl.check(0.002)

    def test_exactly_at_limit_is_allowed(self):
        """境界値: amount == budget_limit は通過する（> ではなく ≥ でないため）"""
        ctrl = SandboxBudgetControl(budget_limit=0.001)
        ctrl.check(0.001)   # must not raise

    def test_well_within_limit_passes(self):
        ctrl = SandboxBudgetControl(budget_limit=1.0)
        ctrl.check(0.001)   # must not raise

    def test_rejection_carries_amount_and_limit(self):
        ctrl = SandboxBudgetControl(budget_limit=0.001)
        with pytest.raises(SandboxBudgetExceededError) as exc_info:
            ctrl.check(0.002)
        exc = exc_info.value
        assert exc.amount == pytest.approx(0.002)
        assert exc.budget_limit == pytest.approx(0.001)

    def test_budget_state_unchanged_on_rejection(self):
        """冪等性: 拒否を繰り返しても閾値は変化しない"""
        ctrl = SandboxBudgetControl(budget_limit=0.001)
        for _ in range(5):
            with pytest.raises(SandboxBudgetExceededError):
                ctrl.check(0.002)
        # 閾値そのものを確認
        assert ctrl.budget_limit == pytest.approx(0.001)

    def test_zero_budget_limit_raises_value_error(self):
        with pytest.raises(ValueError):
            SandboxBudgetControl(budget_limit=0)

    def test_negative_budget_limit_raises_value_error(self):
        with pytest.raises(ValueError):
            SandboxBudgetControl(budget_limit=-0.001)

    def test_budget_limit_property(self):
        ctrl = SandboxBudgetControl(budget_limit=0.05)
        assert ctrl.budget_limit == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Layer 3 — SandboxVerifier 統合
# ---------------------------------------------------------------------------

MERCHANT_URL = "https://sandbox.agentpass.local/api/data"


def _issue(private_key, amount: float):
    req = TokenRequest(
        agent_id="exp005a-agent",
        destination_url=MERCHANT_URL,
        amount_requested=amount,
        purpose="EXP-005a budget test",
        expires_in_seconds=60,
    )
    return issue_token(req, private_key)


class TestSandboxVerifierBudget:
    @pytest.fixture
    def keypair(self):
        return generate_keypair()

    def test_verifier_raises_on_budget_exceeded(self, keypair, tmp_path):
        private_key, public_key = keypair
        issued = _issue(private_key, amount=0.002)

        verifier = SandboxVerifier(
            public_key,
            MERCHANT_URL,
            SandboxBudgetControl(budget_limit=0.001),
            AuditLog(tmp_path / "audit.jsonl"),
        )
        with pytest.raises(SandboxBudgetExceededError):
            verifier.verify(issued.token)

    def test_verifier_http_status_402_on_exceeded(self, keypair, tmp_path):
        private_key, public_key = keypair
        issued = _issue(private_key, amount=0.005)

        verifier = SandboxVerifier(
            public_key,
            MERCHANT_URL,
            SandboxBudgetControl(budget_limit=0.001),
            AuditLog(tmp_path / "audit.jsonl"),
        )
        with pytest.raises(SandboxBudgetExceededError) as exc_info:
            verifier.verify(issued.token)
        assert exc_info.value.http_status == 402

    def test_verifier_within_budget_returns_claims(self, keypair, tmp_path):
        private_key, public_key = keypair
        issued = _issue(private_key, amount=0.001)

        verifier = SandboxVerifier(
            public_key,
            MERCHANT_URL,
            SandboxBudgetControl(budget_limit=0.01),
            AuditLog(tmp_path / "audit.jsonl"),
        )
        claims = verifier.verify(issued.token)
        assert claims.agent_id == "exp005a-agent"
        assert claims.amount == pytest.approx(0.001)

    def test_verifier_budget_exceeded_appends_audit_log(self, keypair, tmp_path):
        private_key, public_key = keypair
        issued = _issue(private_key, amount=0.002)
        log = AuditLog(tmp_path / "audit.jsonl")

        verifier = SandboxVerifier(
            public_key,
            MERCHANT_URL,
            SandboxBudgetControl(budget_limit=0.001),
            log,
        )
        with pytest.raises(SandboxBudgetExceededError):
            verifier.verify(issued.token)

        records = log.read_all()
        assert len(records) == 1
        assert records[0]["event_type"] == "budget_exceeded"

    def test_verifier_success_does_not_append_budget_event(self, keypair, tmp_path):
        private_key, public_key = keypair
        issued = _issue(private_key, amount=0.001)
        log = AuditLog(tmp_path / "audit.jsonl")

        verifier = SandboxVerifier(
            public_key,
            MERCHANT_URL,
            SandboxBudgetControl(budget_limit=0.01),
            log,
        )
        verifier.verify(issued.token)
        assert log.read_all() == []
