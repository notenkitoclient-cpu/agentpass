"""
EXP-005a: audit log の append-only 動作・必須フィールド・JSONL 形式を検証する。
"""

from __future__ import annotations

import json

import pytest

from src.agentpass.sandbox.audit_log import AuditLog, REQUIRED_FIELDS


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def _record(log: AuditLog, *, agent_id: str = "agent-001",
            amount: float = 0.002, budget_limit: float = 0.001,
            nonce: str = "test-nonce") -> dict:
    return log.make_budget_exceeded_record(
        agent_id=agent_id,
        amount=amount,
        budget_limit=budget_limit,
        nonce=nonce,
    )


# ---------------------------------------------------------------------------
# ファイル書き込み
# ---------------------------------------------------------------------------

class TestAuditLogAppend:
    def test_append_creates_file(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        log.append(_record(log))
        assert (tmp_path / "audit.jsonl").exists()

    def test_append_is_cumulative(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        for i in range(5):
            log.append(_record(log, nonce=f"n{i}"))
        assert len(log.read_all()) == 5

    def test_each_line_is_valid_json(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        for i in range(3):
            log.append(_record(log, nonce=f"n{i}"))
        lines = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
        assert len(lines) == 3
        for line in lines:
            json.loads(line)   # must not raise

    def test_append_does_not_overwrite_existing(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        log.append(_record(log, nonce="first"))
        log.append(_record(log, nonce="second"))
        records = log.read_all()
        nonces = [r["nonce"] for r in records]
        assert "first" in nonces
        assert "second" in nonces


# ---------------------------------------------------------------------------
# read_all
# ---------------------------------------------------------------------------

class TestAuditLogReadAll:
    def test_read_all_empty_returns_empty_list(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        assert log.read_all() == []

    def test_read_all_nonexistent_file_returns_empty_list(self, tmp_path):
        log = AuditLog(tmp_path / "does_not_exist.jsonl")
        assert log.read_all() == []

    def test_read_all_returns_list_of_dicts(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        log.append(_record(log))
        result = log.read_all()
        assert isinstance(result, list)
        assert isinstance(result[0], dict)

    def test_read_all_roundtrips_values(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        original = _record(log, agent_id="agent-xyz", amount=3.14, budget_limit=1.0)
        log.append(original)
        recovered = log.read_all()[0]
        assert recovered["agent_id"] == "agent-xyz"
        assert recovered["amount"] == pytest.approx(3.14)
        assert recovered["budget_limit"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# make_budget_exceeded_record — 必須フィールドと値
# ---------------------------------------------------------------------------

class TestMakeBudgetExceededRecord:
    def test_all_required_fields_present(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        r = _record(log)
        missing = REQUIRED_FIELDS - r.keys()
        assert not missing, f"Missing required fields: {missing}"

    def test_event_type_is_budget_exceeded(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        assert _record(log)["event_type"] == "budget_exceeded"

    def test_status_is_rejected(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        assert _record(log)["status"] == "rejected"

    def test_reason_is_budget_exceeded(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        assert _record(log)["reason"] == "budget_exceeded"

    def test_event_id_is_unique(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        ids = {_record(log)["event_id"] for _ in range(10)}
        assert len(ids) == 10   # all unique

    def test_timestamp_format(self, tmp_path):
        import re
        log = AuditLog(tmp_path / "audit.jsonl")
        ts = _record(log)["timestamp"]
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts), \
            f"Unexpected timestamp format: {ts}"

    def test_amount_and_budget_limit_stored_correctly(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        r = _record(log, amount=0.005, budget_limit=0.001)
        assert r["amount"] == pytest.approx(0.005)
        assert r["budget_limit"] == pytest.approx(0.001)

    def test_nonce_stored(self, tmp_path):
        log = AuditLog(tmp_path / "audit.jsonl")
        r = _record(log, nonce="my-unique-nonce")
        assert r["nonce"] == "my-unique-nonce"
