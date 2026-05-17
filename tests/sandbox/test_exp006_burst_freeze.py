"""
EXP-006: Replay burst detection and spending freeze tests.

Verifies that BurstFreezeDetector correctly counts replay events in a
sliding window, triggers a temporary freeze, and that FreezeLayer enforces
the freeze without modifying SandboxVerifier or ReplayGuard.

Test classes:
  1. TestBurstFreezeDetector  — unit: sliding window, threshold, freeze state
  2. TestFreezeLayer          — integration: normal pass-through, burst → freeze
  3. TestAuditLogFreezeEvent  — audit: spending_frozen record structure
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.agentpass.sandbox.audit_log import AuditLog
from src.agentpass.sandbox.budget_control import SandboxBudgetControl
from src.agentpass.sandbox.burst_freeze import BurstFreezeDetector
from src.agentpass.sandbox.errors import SpendingFrozenError
from src.agentpass.sandbox.freeze_layer import FreezeLayer
from src.agentpass.sandbox.replay_guard import ReplayGuard
from src.agentpass.sandbox.verifier import SandboxVerifier
from src.core.token_issuer import TokenRequest, generate_keypair, issue_token
from src.core.token_verifier import InvalidPayloadError


MERCHANT_URL = "https://sandbox.agentpass.local/api/data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_freeze_layer(
    tmp_path: Path,
    threshold: int = 3,
    window_seconds: float = 60.0,
    freeze_seconds: float = 30.0,
    budget_limit: float = 10.0,
) -> tuple[FreezeLayer, AuditLog, object]:
    """Return (freeze_layer, audit_log, private_key)."""
    private_key, public_key = generate_keypair()
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    budget_control = SandboxBudgetControl(budget_limit)
    guard = ReplayGuard()
    inner = SandboxVerifier(
        public_key=public_key,
        merchant_url=MERCHANT_URL,
        budget_control=budget_control,
        audit_log=audit_log,
        replay_guard=guard,
    )
    burst = BurstFreezeDetector(
        threshold=threshold,
        window_seconds=window_seconds,
        freeze_seconds=freeze_seconds,
    )
    layer = FreezeLayer(inner=inner, burst=burst, audit_log=audit_log)
    return layer, audit_log, private_key


def _issue_token(private_key, amount: float = 0.001) -> str:
    req = TokenRequest(
        agent_id="exp006-agent",
        destination_url=MERCHANT_URL,
        amount_requested=amount,
        purpose="EXP-006 freeze test",
        expires_in_seconds=60,
    )
    return issue_token(req, private_key).token


# ---------------------------------------------------------------------------
# Class 1: BurstFreezeDetector unit tests
# ---------------------------------------------------------------------------

class TestBurstFreezeDetector:
    """Unit tests for sliding-window counter and freeze state."""

    def test_not_frozen_initially(self):
        det = BurstFreezeDetector(threshold=3, window_seconds=1.0)
        assert not det.is_frozen()

    def test_below_threshold_does_not_freeze(self):
        det = BurstFreezeDetector(threshold=3, window_seconds=1.0)
        det.record_replay(now=0.0)
        det.record_replay(now=0.1)
        assert not det.is_frozen(now=0.2)

    def test_at_threshold_triggers_freeze(self):
        det = BurstFreezeDetector(threshold=3, window_seconds=1.0, freeze_seconds=10.0)
        det.record_replay(now=0.0)
        det.record_replay(now=0.1)
        just_frozen = det.record_replay(now=0.2)
        assert just_frozen is True
        assert det.is_frozen(now=0.3)

    def test_record_replay_returns_false_before_threshold(self):
        det = BurstFreezeDetector(threshold=3, window_seconds=1.0)
        assert det.record_replay(now=0.0) is False
        assert det.record_replay(now=0.1) is False

    def test_record_replay_returns_false_when_already_frozen(self):
        det = BurstFreezeDetector(threshold=2, window_seconds=1.0, freeze_seconds=10.0)
        det.record_replay(now=0.0)
        det.record_replay(now=0.1)  # triggers freeze
        # Additional replays while frozen should return False (freeze already active)
        result = det.record_replay(now=0.2)
        assert result is False

    def test_freeze_expires_after_freeze_seconds(self):
        det = BurstFreezeDetector(threshold=2, window_seconds=60.0, freeze_seconds=5.0)
        det.record_replay(now=0.0)
        det.record_replay(now=0.1)  # freeze triggered at t=0.1, unfreezes at t=5.1
        assert det.is_frozen(now=4.9)
        assert not det.is_frozen(now=5.2)

    def test_window_expiry_resets_count(self):
        det = BurstFreezeDetector(threshold=3, window_seconds=1.0, freeze_seconds=10.0)
        det.record_replay(now=0.0)
        det.record_replay(now=0.1)
        # Events at t=0.0 and t=0.1 fall outside window at t=1.5
        assert det.replay_count_in_window(now=1.5) == 0

    def test_replay_count_in_window_includes_only_recent(self):
        det = BurstFreezeDetector(threshold=10, window_seconds=1.0)
        det.record_replay(now=0.0)   # outside at t=2.0
        det.record_replay(now=1.5)   # inside at t=2.0
        det.record_replay(now=1.8)   # inside at t=2.0
        assert det.replay_count_in_window(now=2.0) == 2

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError, match="threshold"):
            BurstFreezeDetector(threshold=0, window_seconds=1.0)

    def test_invalid_window_raises(self):
        with pytest.raises(ValueError, match="window_seconds"):
            BurstFreezeDetector(threshold=1, window_seconds=0.0)

    def test_concurrent_record_replay_exactly_one_triggers(self):
        """Under concurrency, exactly one record_replay() returns True at threshold."""
        det = BurstFreezeDetector(threshold=5, window_seconds=60.0, freeze_seconds=30.0)
        triggers = []
        lock = threading.Lock()

        def fire():
            result = det.record_replay()
            if result:
                with lock:
                    triggers.append(1)

        threads = [threading.Thread(target=fire) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(triggers) == 1


# ---------------------------------------------------------------------------
# Class 2: FreezeLayer integration tests
# ---------------------------------------------------------------------------

class TestFreezeLayer:
    """End-to-end: normal → pass-through; replay burst → freeze."""

    def test_normal_request_passes_through(self, tmp_path):
        layer, _, private_key = _make_freeze_layer(tmp_path)
        token = _issue_token(private_key)
        claims = layer.verify(token)
        assert claims.agent_id == "exp006-agent"

    def test_single_replay_does_not_freeze(self, tmp_path):
        layer, _, private_key = _make_freeze_layer(tmp_path, threshold=3)
        token = _issue_token(private_key)
        layer.verify(token)  # first — OK
        with pytest.raises(InvalidPayloadError):
            layer.verify(token)  # replay — rejected but no freeze yet
        # next fresh token should still work
        token2 = _issue_token(private_key)
        claims = layer.verify(token2)
        assert claims.agent_id == "exp006-agent"

    def test_burst_triggers_freeze(self, tmp_path):
        layer, _, private_key = _make_freeze_layer(tmp_path, threshold=3)
        # Issue 3 tokens and replay each once to accumulate 3 replay_detected events
        for _ in range(3):
            token = _issue_token(private_key)
            layer.verify(token)
            with pytest.raises(InvalidPayloadError):
                layer.verify(token)

        # Next fresh request must be blocked by freeze
        fresh = _issue_token(private_key)
        with pytest.raises(SpendingFrozenError):
            layer.verify(fresh)

    def test_frozen_error_has_correct_http_status(self, tmp_path):
        layer, _, private_key = _make_freeze_layer(tmp_path, threshold=2)
        for _ in range(2):
            token = _issue_token(private_key)
            layer.verify(token)
            with pytest.raises(InvalidPayloadError):
                layer.verify(token)
        fresh = _issue_token(private_key)
        with pytest.raises(SpendingFrozenError) as exc_info:
            layer.verify(fresh)
        assert exc_info.value.http_status == 503

    def test_frozen_error_to_response(self, tmp_path):
        layer, _, private_key = _make_freeze_layer(tmp_path, threshold=2)
        for _ in range(2):
            token = _issue_token(private_key)
            layer.verify(token)
            with pytest.raises(InvalidPayloadError):
                layer.verify(token)
        fresh = _issue_token(private_key)
        with pytest.raises(SpendingFrozenError) as exc_info:
            layer.verify(fresh)
        response = exc_info.value.to_response()
        assert response["status"] == "frozen"
        assert response["reason"] == "replay_burst_detected"

    def test_normal_requests_before_burst_all_succeed(self, tmp_path):
        layer, _, private_key = _make_freeze_layer(tmp_path, threshold=5)
        for _ in range(4):
            token = _issue_token(private_key)
            claims = layer.verify(token)
            assert claims.agent_id == "exp006-agent"


# ---------------------------------------------------------------------------
# Class 3: Audit log spending_frozen event tests
# ---------------------------------------------------------------------------

class TestAuditLogFreezeEvent:
    """Verify spending_frozen records are written at the right moments."""

    def test_make_spending_frozen_record_fields(self):
        record = AuditLog.make_spending_frozen_record(burst_count=3, nonce="n-001")
        assert record["event_type"] == "spending_frozen"
        assert record["status"] == "frozen"
        assert record["reason"] == "replay_burst_detected"
        assert record["burst_count"] == 3
        assert record["nonce"] == "n-001"
        assert "event_id" in record
        assert "timestamp" in record

    def test_freeze_trigger_writes_spending_frozen_to_audit(self, tmp_path):
        layer, audit_log, private_key = _make_freeze_layer(tmp_path, threshold=2)
        for _ in range(2):
            token = _issue_token(private_key)
            layer.verify(token)
            with pytest.raises(InvalidPayloadError):
                layer.verify(token)
        events = audit_log.read_all()
        frozen_events = [e for e in events if e["event_type"] == "spending_frozen"]
        assert len(frozen_events) == 1

    def test_pre_frozen_request_also_writes_spending_frozen(self, tmp_path):
        layer, audit_log, private_key = _make_freeze_layer(tmp_path, threshold=2)
        # Trigger freeze
        for _ in range(2):
            token = _issue_token(private_key)
            layer.verify(token)
            with pytest.raises(InvalidPayloadError):
                layer.verify(token)
        # Now attempt a fresh request while frozen — should also write spending_frozen
        fresh = _issue_token(private_key)
        with pytest.raises(SpendingFrozenError):
            layer.verify(fresh)
        events = audit_log.read_all()
        frozen_events = [e for e in events if e["event_type"] == "spending_frozen"]
        assert len(frozen_events) == 2  # once at trigger, once at gate check

    def test_spending_frozen_record_burst_count_nonzero(self, tmp_path):
        layer, audit_log, private_key = _make_freeze_layer(tmp_path, threshold=2)
        for _ in range(2):
            token = _issue_token(private_key)
            layer.verify(token)
            with pytest.raises(InvalidPayloadError):
                layer.verify(token)
        events = audit_log.read_all()
        frozen = [e for e in events if e["event_type"] == "spending_frozen"][0]
        assert frozen["burst_count"] >= 2

    def test_no_freeze_event_without_burst(self, tmp_path):
        layer, audit_log, private_key = _make_freeze_layer(tmp_path, threshold=5)
        # 2 replays — below threshold of 5
        for _ in range(2):
            token = _issue_token(private_key)
            layer.verify(token)
            with pytest.raises(InvalidPayloadError):
                layer.verify(token)
        events = audit_log.read_all()
        frozen_events = [e for e in events if e["event_type"] == "spending_frozen"]
        assert len(frozen_events) == 0
