"""
EXP-005a: audit log からの replay 検証

「budget_exceeded イベントを audit log から読み込み、
 同じ条件で SandboxBudgetControl を再実行すると同じ拒否が再現される」
ことを確認する。

2層:
  Layer 1 — AuditLog + SandboxBudgetControl だけを使った純粋な replay 単体テスト
  Layer 2 — SandboxVerifier 経由で記録されたイベントの replay 統合テスト
"""

from __future__ import annotations

import pytest

from src.agentpass.sandbox.audit_log import AuditLog
from src.agentpass.sandbox.budget_control import SandboxBudgetControl
from src.agentpass.sandbox.errors import SandboxBudgetExceededError
from src.agentpass.sandbox.verifier import SandboxVerifier
from src.core.token_issuer import TokenRequest, generate_keypair, issue_token


MERCHANT_URL = "https://sandbox.agentpass.local/api/data"


def _issue(private_key, amount: float):
    req = TokenRequest(
        agent_id="replay-agent",
        destination_url=MERCHANT_URL,
        amount_requested=amount,
        purpose="EXP-005a replay test",
        expires_in_seconds=60,
    )
    return issue_token(req, private_key)


# ---------------------------------------------------------------------------
# Layer 1 — AuditLog + SandboxBudgetControl の純粋 replay
# ---------------------------------------------------------------------------

class TestBudgetReplayFromAuditLog:
    def test_rejection_is_replayable(self, tmp_path):
        """audit log のレコードから同じ拒否を再現できる"""
        log = AuditLog(tmp_path / "audit.jsonl")
        record = log.make_budget_exceeded_record(
            agent_id="agent-001", amount=0.002,
            budget_limit=0.001, nonce="nonce-1",
        )
        log.append(record)

        r = log.read_all()[0]
        ctrl = SandboxBudgetControl(budget_limit=r["budget_limit"])

        with pytest.raises(SandboxBudgetExceededError) as exc_info:
            ctrl.check(r["amount"])

        exc = exc_info.value
        assert exc.amount == pytest.approx(r["amount"])
        assert exc.budget_limit == pytest.approx(r["budget_limit"])

    def test_replay_preserves_all_original_fields(self, tmp_path):
        """replay したイベントの主要フィールドが元のレコードと一致する"""
        log = AuditLog(tmp_path / "audit.jsonl")
        original = log.make_budget_exceeded_record(
            agent_id="agent-replay", amount=5.0,
            budget_limit=1.0, nonce="nonce-xyz",
        )
        log.append(original)

        replayed = log.read_all()[0]
        for field in ("agent_id", "amount", "budget_limit",
                      "status", "reason", "event_type", "nonce"):
            assert replayed[field] == original[field], \
                f"Field {field!r} changed after round-trip"

    def test_multiple_rejections_all_replayable(self, tmp_path):
        """複数の rejection レコードがすべて replay できる"""
        log = AuditLog(tmp_path / "audit.jsonl")
        cases = [
            {"agent_id": "a", "amount": 0.5,  "budget_limit": 0.1},
            {"agent_id": "b", "amount": 10.0, "budget_limit": 5.0},
            {"agent_id": "c", "amount": 1.01, "budget_limit": 1.0},
        ]
        for c in cases:
            log.append(log.make_budget_exceeded_record(nonce="n", **c))

        for r in log.read_all():
            ctrl = SandboxBudgetControl(budget_limit=r["budget_limit"])
            with pytest.raises(SandboxBudgetExceededError):
                ctrl.check(r["amount"])

    def test_within_budget_does_not_replay_as_rejection(self, tmp_path):
        """budget 内の amount は replay しても拒否されない"""
        log = AuditLog(tmp_path / "audit.jsonl")
        ctrl = SandboxBudgetControl(budget_limit=0.01)
        ctrl.check(0.001)   # passes — no rejection to replay
        assert log.read_all() == []

    def test_replay_idempotent_across_multiple_runs(self, tmp_path):
        """同じレコードで何度 replay しても結果が変わらない"""
        log = AuditLog(tmp_path / "audit.jsonl")
        record = log.make_budget_exceeded_record(
            agent_id="agent-idempotent", amount=2.0,
            budget_limit=1.0, nonce="nonce-idem",
        )
        log.append(record)

        r = log.read_all()[0]
        for _ in range(5):
            ctrl = SandboxBudgetControl(budget_limit=r["budget_limit"])
            with pytest.raises(SandboxBudgetExceededError):
                ctrl.check(r["amount"])


# ---------------------------------------------------------------------------
# Layer 2 — SandboxVerifier 経由で記録されたイベントの replay 統合テスト
# ---------------------------------------------------------------------------

class TestBudgetReplayViaVerifier:
    @pytest.fixture
    def keypair(self):
        return generate_keypair()

    def test_verifier_rejection_is_replayable(self, keypair, tmp_path):
        """Verifier が記録した budget_exceeded を audit log から replay できる"""
        private_key, public_key = keypair
        issued = _issue(private_key, amount=0.005)
        log = AuditLog(tmp_path / "audit.jsonl")

        verifier = SandboxVerifier(
            public_key, MERCHANT_URL,
            SandboxBudgetControl(budget_limit=0.001), log,
        )
        with pytest.raises(SandboxBudgetExceededError):
            verifier.verify(issued.token)

        r = log.read_all()[0]
        ctrl = SandboxBudgetControl(budget_limit=r["budget_limit"])

        with pytest.raises(SandboxBudgetExceededError) as exc_info:
            ctrl.check(r["amount"])

        assert exc_info.value.amount == pytest.approx(r["amount"])
        assert exc_info.value.budget_limit == pytest.approx(r["budget_limit"])

    def test_verifier_audit_record_contains_agent_id(self, keypair, tmp_path):
        """Verifier が記録した audit レコードに agent_id が含まれる"""
        private_key, public_key = keypair
        issued = _issue(private_key, amount=0.002)
        log = AuditLog(tmp_path / "audit.jsonl")

        verifier = SandboxVerifier(
            public_key, MERCHANT_URL,
            SandboxBudgetControl(budget_limit=0.001), log,
        )
        with pytest.raises(SandboxBudgetExceededError):
            verifier.verify(issued.token)

        r = log.read_all()[0]
        assert r["agent_id"] == "replay-agent"
        assert r["amount"] == pytest.approx(0.002)
        assert r["budget_limit"] == pytest.approx(0.001)

    def test_replay_response_body_matches_spec(self, keypair, tmp_path):
        """replay 時の to_response() が仕様通りの形式を返す"""
        private_key, public_key = keypair
        issued = _issue(private_key, amount=0.999)
        log = AuditLog(tmp_path / "audit.jsonl")

        verifier = SandboxVerifier(
            public_key, MERCHANT_URL,
            SandboxBudgetControl(budget_limit=0.001), log,
        )
        with pytest.raises(SandboxBudgetExceededError):
            verifier.verify(issued.token)

        r = log.read_all()[0]
        ctrl = SandboxBudgetControl(budget_limit=r["budget_limit"])
        with pytest.raises(SandboxBudgetExceededError) as exc_info:
            ctrl.check(r["amount"])

        body = exc_info.value.to_response()
        assert body == {
            "status": "rejected",
            "reason": "budget_exceeded",
            "error": "BudgetExceededError",
        }
