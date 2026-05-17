"""
EXP-005b: JTI collision / double-spend prevention tests.

Verifies that ReplayGuard correctly prevents the same JTI from being
accepted twice, even under concurrent requests.

3 test classes:
  1. TestSequentialReplay   — same token used twice sequentially → 2nd is rejected
  2. TestParallelCollision  — same token sent by N threads → exactly 1 approved
  3. TestAuditLogEvents     — audit log contains purchase_approved + replay_detected
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agentpass.sandbox.audit_log import AuditLog
from agentpass.sandbox.budget_control import SandboxBudgetControl
from agentpass.sandbox.replay_guard import ReplayGuard
from agentpass.sandbox.verifier import SandboxVerifier
from core.token_issuer import TokenRequest, generate_keypair, issue_token
from core.token_verifier import InvalidPayloadError


MERCHANT_URL = "https://sandbox.agentpass.local/api/data"


def _make_verifier(
    tmp_path: Path,
    budget_limit: float = 1.0,
    replay_guard: ReplayGuard | None = None,
) -> tuple[SandboxVerifier, AuditLog]:
    private_key, public_key = generate_keypair()
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    budget_control = SandboxBudgetControl(budget_limit)
    verifier = SandboxVerifier(
        public_key=public_key,
        merchant_url=MERCHANT_URL,
        budget_control=budget_control,
        audit_log=audit_log,
        replay_guard=replay_guard,
    )
    return verifier, audit_log, private_key


def _issue_token(private_key, amount: float = 0.001) -> str:
    req = TokenRequest(
        agent_id="exp005b-agent",
        destination_url=MERCHANT_URL,
        amount_requested=amount,
        purpose="EXP-005b collision test",
        expires_in_seconds=60,
    )
    return issue_token(req, private_key).token


# ---------------------------------------------------------------------------
# Class 1: Sequential replay
# ---------------------------------------------------------------------------

class TestSequentialReplay:
    """Same token presented twice in sequence — second must be rejected."""

    def test_first_call_succeeds(self, tmp_path):
        guard = ReplayGuard()
        verifier, _, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token = _issue_token(private_key)
        claims = verifier.verify(token)
        assert claims.agent_id == "exp005b-agent"

    def test_second_call_raises_invalid_payload(self, tmp_path):
        guard = ReplayGuard()
        verifier, _, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token = _issue_token(private_key)
        verifier.verify(token)  # first — OK
        with pytest.raises(InvalidPayloadError, match="Replay attack detected"):
            verifier.verify(token)  # second — must fail

    def test_different_tokens_both_succeed(self, tmp_path):
        guard = ReplayGuard()
        verifier, _, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token_a = _issue_token(private_key)
        token_b = _issue_token(private_key)
        claims_a = verifier.verify(token_a)
        claims_b = verifier.verify(token_b)
        assert claims_a.token_id != claims_b.token_id

    def test_replay_guard_check_and_register_first_is_true(self):
        guard = ReplayGuard()
        assert guard.check_and_register("jti-abc") is True

    def test_replay_guard_check_and_register_second_is_false(self):
        guard = ReplayGuard()
        guard.check_and_register("jti-abc")
        assert guard.check_and_register("jti-abc") is False

    def test_replay_guard_independent_jtis(self):
        guard = ReplayGuard()
        assert guard.check_and_register("jti-1") is True
        assert guard.check_and_register("jti-2") is True
        assert guard.check_and_register("jti-1") is False


# ---------------------------------------------------------------------------
# Class 2: Parallel collision (threading)
# ---------------------------------------------------------------------------

class TestParallelCollision:
    """
    Same token sent by multiple concurrent threads.
    Exactly one thread must succeed; all others must be rejected.
    """

    def _run_parallel(
        self,
        verifier: SandboxVerifier,
        token: str,
        n_threads: int,
    ) -> tuple[int, int]:
        """Return (approved_count, rejected_count)."""
        approved = []
        rejected = []
        lock = threading.Lock()

        def call():
            try:
                verifier.verify(token)
                with lock:
                    approved.append(1)
            except InvalidPayloadError:
                with lock:
                    rejected.append(1)

        threads = [threading.Thread(target=call) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        return len(approved), len(rejected)

    def test_two_concurrent_exactly_one_approved(self, tmp_path):
        guard = ReplayGuard()
        verifier, _, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token = _issue_token(private_key)
        approved, rejected = self._run_parallel(verifier, token, n_threads=2)
        assert approved == 1
        assert rejected == 1

    def test_ten_concurrent_exactly_one_approved(self, tmp_path):
        guard = ReplayGuard()
        verifier, _, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token = _issue_token(private_key)
        approved, rejected = self._run_parallel(verifier, token, n_threads=10)
        assert approved == 1
        assert rejected == 9

    def test_guard_alone_concurrent_one_true(self):
        """ReplayGuard in isolation: N concurrent check_and_register → 1 True."""
        guard = ReplayGuard()
        results = []
        lock = threading.Lock()

        def check():
            result = guard.check_and_register("shared-jti")
            with lock:
                results.append(result)

        threads = [threading.Thread(target=check) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
        assert results.count(False) == 19


# ---------------------------------------------------------------------------
# Class 3: Audit log events
# ---------------------------------------------------------------------------

class TestAuditLogEvents:
    """Verify that purchase_approved and replay_detected events are written."""

    def test_successful_verify_writes_purchase_approved(self, tmp_path):
        guard = ReplayGuard()
        verifier, audit_log, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token = _issue_token(private_key)
        verifier.verify(token)
        events = audit_log.read_all()
        assert len(events) == 1
        assert events[0]["event_type"] == "purchase_approved"
        assert events[0]["status"] == "approved"

    def test_replay_writes_replay_detected(self, tmp_path):
        guard = ReplayGuard()
        verifier, audit_log, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token = _issue_token(private_key)
        verifier.verify(token)  # approved
        with pytest.raises(InvalidPayloadError):
            verifier.verify(token)  # replay
        events = audit_log.read_all()
        event_types = [e["event_type"] for e in events]
        assert "purchase_approved" in event_types
        assert "replay_detected" in event_types

    def test_purchase_approved_contains_token_id(self, tmp_path):
        guard = ReplayGuard()
        verifier, audit_log, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token = _issue_token(private_key)
        claims = verifier.verify(token)
        events = audit_log.read_all()
        approved = [e for e in events if e["event_type"] == "purchase_approved"]
        assert approved[0]["token_id"] == claims.token_id

    def test_replay_detected_contains_token_id(self, tmp_path):
        guard = ReplayGuard()
        verifier, audit_log, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token = _issue_token(private_key)
        claims = verifier.verify(token)
        with pytest.raises(InvalidPayloadError):
            verifier.verify(token)
        events = audit_log.read_all()
        detected = [e for e in events if e["event_type"] == "replay_detected"]
        assert detected[0]["token_id"] == claims.token_id

    def test_replay_detected_status_is_rejected(self, tmp_path):
        guard = ReplayGuard()
        verifier, audit_log, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token = _issue_token(private_key)
        verifier.verify(token)
        with pytest.raises(InvalidPayloadError):
            verifier.verify(token)
        events = audit_log.read_all()
        detected = [e for e in events if e["event_type"] == "replay_detected"]
        assert detected[0]["status"] == "rejected"
        assert detected[0]["reason"] == "replay_detected"

    def test_no_guard_no_purchase_approved_log(self, tmp_path):
        """Without replay_guard, success logging remains caller's responsibility."""
        verifier, audit_log, private_key = _make_verifier(tmp_path, replay_guard=None)
        token = _issue_token(private_key)
        verifier.verify(token)
        events = audit_log.read_all()
        assert events == []

    def test_parallel_audit_log_has_one_approved_one_rejected(self, tmp_path):
        """Under concurrent load, audit log has 1 approved + 1 rejected (2 threads)."""
        guard = ReplayGuard()
        verifier, audit_log, private_key = _make_verifier(tmp_path, replay_guard=guard)
        token = _issue_token(private_key)

        barrier = threading.Barrier(2)
        results = []
        lock = threading.Lock()

        def call():
            barrier.wait()
            try:
                verifier.verify(token)
                with lock:
                    results.append("approved")
            except InvalidPayloadError:
                with lock:
                    results.append("rejected")

        threads = [threading.Thread(target=call) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = audit_log.read_all()
        event_types = [e["event_type"] for e in events]
        assert event_types.count("purchase_approved") == 1
        assert event_types.count("replay_detected") == 1
