"""
EXP-005c: Agent keypair isolation tests.

Verifies that each agent's signing key is independently scoped, that a
compromised key does not affect other agents, and that signer identity is
traceable via the audit log.

Test classes:
  1. TestAgentKeyRegistry        — unit: register, resolve, compromised, status
  2. TestSandboxSigner           — unit: sign, kid header, agent_id guard
  3. TestMultiAgentVerification  — integration: isolation, mismatch, compromised
  4. TestAuditLogSignerEvents    — audit: signer_verified / signer_rejected records
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest

from agentpass.sandbox.agent_key_registry import AgentKeyRegistry
from agentpass.sandbox.audit_log import AuditLog
from agentpass.sandbox.budget_control import SandboxBudgetControl
from agentpass.sandbox.errors import (
    CompromisedKeyError,
    SignerMismatchError,
    UnknownKeyIdError,
)
from agentpass.sandbox.replay_guard import ReplayGuard
from agentpass.sandbox.signer import SandboxSigner
from agentpass.sandbox.verifier import SandboxVerifier
from core.token_issuer import TokenRequest, generate_keypair


MERCHANT_URL = "https://sandbox.agentpass.local/api/data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signer(agent_id: str, key_id: str) -> tuple[SandboxSigner, object]:
    """Return (signer, public_key) for an agent."""
    private_key, public_key = generate_keypair()
    return SandboxSigner(agent_id, key_id, private_key), public_key


def _make_registry(*entries: tuple[str, str, SandboxSigner, object]) -> AgentKeyRegistry:
    """
    Build a registry from (agent_id, key_id, signer, public_key) tuples.
    entries = [("agent-a", "key-a", signer_a, pub_a), ...]
    """
    registry = AgentKeyRegistry()
    for agent_id, key_id, _, public_key in entries:
        registry.register(agent_id, key_id, public_key)
    return registry


def _make_verifier(
    tmp_path: Path,
    registry: AgentKeyRegistry,
    budget_limit: float = 10.0,
) -> tuple[SandboxVerifier, AuditLog]:
    audit_log = AuditLog(tmp_path / "audit.jsonl")
    budget_control = SandboxBudgetControl(budget_limit)
    guard = ReplayGuard()
    verifier = SandboxVerifier(
        public_key=None,          # ignored when key_registry is provided
        merchant_url=MERCHANT_URL,
        budget_control=budget_control,
        audit_log=audit_log,
        replay_guard=guard,
        key_registry=registry,
    )
    return verifier, audit_log


def _req(agent_id: str) -> TokenRequest:
    return TokenRequest(
        agent_id=agent_id,
        destination_url=MERCHANT_URL,
        amount_requested=0.001,
        purpose="EXP-005c isolation test",
        expires_in_seconds=60,
    )


def _forge_token(private_key, key_id: str, claimed_agent_id: str) -> str:
    """
    Create a JWT that claims to be from claimed_agent_id but is signed with
    a different agent's private key. Used to test signer_mismatch rejection.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": claimed_agent_id,
        "aud": MERCHANT_URL,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=60)).timestamp()),
        "jti": str(uuid.uuid4()),
        "amt": 0.001,
        "cur": "JPY",
        "agp": "1",
    }
    return jwt.encode(payload, private_key, algorithm="EdDSA", headers={"kid": key_id})


# ---------------------------------------------------------------------------
# Class 1: AgentKeyRegistry
# ---------------------------------------------------------------------------

class TestAgentKeyRegistry:
    """Unit tests for key registration, resolution, and compromised state."""

    def test_register_and_resolve_returns_agent_and_key(self):
        registry = AgentKeyRegistry()
        _, pub = generate_keypair()
        registry.register("agent-a", "key-a-001", pub)
        owner, resolved_key = registry.resolve("key-a-001")
        assert owner == "agent-a"
        assert resolved_key is pub

    def test_unknown_key_id_raises(self):
        registry = AgentKeyRegistry()
        with pytest.raises(UnknownKeyIdError) as exc_info:
            registry.resolve("nonexistent-key")
        assert exc_info.value.key_id == "nonexistent-key"

    def test_key_status_active_initially(self):
        registry = AgentKeyRegistry()
        _, pub = generate_keypair()
        registry.register("agent-a", "key-a-001", pub)
        assert registry.key_status("key-a-001") == "active"

    def test_mark_compromised_changes_status(self):
        registry = AgentKeyRegistry()
        _, pub = generate_keypair()
        registry.register("agent-a", "key-a-001", pub)
        registry.mark_compromised("key-a-001")
        assert registry.key_status("key-a-001") == "compromised"

    def test_compromised_key_raises_on_resolve(self):
        registry = AgentKeyRegistry()
        _, pub = generate_keypair()
        registry.register("agent-a", "key-a-001", pub)
        registry.mark_compromised("key-a-001")
        with pytest.raises(CompromisedKeyError) as exc_info:
            registry.resolve("key-a-001")
        assert exc_info.value.key_id == "key-a-001"

    def test_mark_compromised_unknown_key_raises(self):
        registry = AgentKeyRegistry()
        with pytest.raises(UnknownKeyIdError):
            registry.mark_compromised("no-such-key")

    def test_different_agents_have_independent_keys(self):
        registry = AgentKeyRegistry()
        _, pub_a = generate_keypair()
        _, pub_b = generate_keypair()
        registry.register("agent-a", "key-a", pub_a)
        registry.register("agent-b", "key-b", pub_b)
        owner_a, key_a = registry.resolve("key-a")
        owner_b, key_b = registry.resolve("key-b")
        assert owner_a == "agent-a"
        assert owner_b == "agent-b"
        assert key_a is not key_b

    def test_compromising_one_key_does_not_affect_another(self):
        registry = AgentKeyRegistry()
        _, pub_a = generate_keypair()
        _, pub_b = generate_keypair()
        registry.register("agent-a", "key-a", pub_a)
        registry.register("agent-b", "key-b", pub_b)
        registry.mark_compromised("key-a")
        # agent-b's key is still active
        owner_b, _ = registry.resolve("key-b")
        assert owner_b == "agent-b"


# ---------------------------------------------------------------------------
# Class 2: SandboxSigner
# ---------------------------------------------------------------------------

class TestSandboxSigner:
    """Unit tests for per-agent JWT signing with kid header."""

    def test_signed_token_has_kid_in_header(self):
        signer, _ = _make_signer("agent-a", "key-a-001")
        token = signer.sign(_req("agent-a"))
        header = jwt.get_unverified_header(token)
        assert header["kid"] == "key-a-001"

    def test_signed_token_sub_matches_agent_id(self):
        signer, pub = _make_signer("agent-a", "key-a-001")
        token = signer.sign(_req("agent-a"))
        # Decode without verification just to check sub
        payload = jwt.decode(token, pub, algorithms=["EdDSA"], audience=MERCHANT_URL)
        assert payload["sub"] == "agent-a"

    def test_sign_verifiable_by_correct_public_key(self):
        signer, pub = _make_signer("agent-a", "key-a-001")
        token = signer.sign(_req("agent-a"))
        payload = jwt.decode(token, pub, algorithms=["EdDSA"], audience=MERCHANT_URL)
        assert payload["amt"] == 0.001

    def test_sign_not_verifiable_by_different_key(self):
        signer, _ = _make_signer("agent-a", "key-a-001")
        _, other_pub = generate_keypair()
        token = signer.sign(_req("agent-a"))
        with pytest.raises(jwt.exceptions.InvalidSignatureError):
            jwt.decode(token, other_pub, algorithms=["EdDSA"], audience=MERCHANT_URL)

    def test_sign_wrong_agent_id_raises(self):
        signer, _ = _make_signer("agent-a", "key-a-001")
        wrong_req = _req("agent-b")
        with pytest.raises(ValueError, match="agent_id"):
            signer.sign(wrong_req)

    def test_signer_properties(self):
        signer, _ = _make_signer("agent-a", "key-a-001")
        assert signer.agent_id == "agent-a"
        assert signer.key_id == "key-a-001"


# ---------------------------------------------------------------------------
# Class 3: Multi-agent verification
# ---------------------------------------------------------------------------

class TestMultiAgentVerification:
    """Integration: correct isolation, mismatch rejection, compromised isolation."""

    def test_agent_a_token_verified_by_agent_a_key(self, tmp_path):
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", pub_a)
        verifier, _ = _make_verifier(tmp_path, registry)
        token = signer_a.sign(_req("agent-a"))
        claims = verifier.verify(token)
        assert claims.agent_id == "agent-a"

    def test_agent_b_token_verified_by_agent_b_key(self, tmp_path):
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        signer_b, pub_b = _make_signer("agent-b", "key-b")
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", pub_a)
        registry.register("agent-b", "key-b", pub_b)
        verifier, _ = _make_verifier(tmp_path, registry)
        token_b = signer_b.sign(_req("agent-b"))
        claims = verifier.verify(token_b)
        assert claims.agent_id == "agent-b"

    def test_signer_mismatch_rejected(self, tmp_path):
        """agent_id=A in sub but token signed with key-B → SignerMismatchError."""
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        priv_b, pub_b = generate_keypair()
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", pub_a)
        registry.register("agent-b", "key-b", pub_b)
        verifier, _ = _make_verifier(tmp_path, registry)
        forged = _forge_token(priv_b, "key-b", "agent-a")
        with pytest.raises(SignerMismatchError) as exc_info:
            verifier.verify(forged)
        assert exc_info.value.claimed_agent_id == "agent-a"
        assert exc_info.value.key_owner_agent_id == "agent-b"

    def test_compromised_key_rejected(self, tmp_path):
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", pub_a)
        registry.mark_compromised("key-a")
        verifier, _ = _make_verifier(tmp_path, registry)
        token = signer_a.sign(_req("agent-a"))
        with pytest.raises(CompromisedKeyError):
            verifier.verify(token)

    def test_compromised_agent_a_does_not_affect_agent_b(self, tmp_path):
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        signer_b, pub_b = _make_signer("agent-b", "key-b")
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", pub_a)
        registry.register("agent-b", "key-b", pub_b)
        registry.mark_compromised("key-a")
        verifier, _ = _make_verifier(tmp_path, registry)
        # agent-a is compromised — rejected
        with pytest.raises(CompromisedKeyError):
            verifier.verify(signer_a.sign(_req("agent-a")))
        # agent-b is still active — approved
        claims = verifier.verify(signer_b.sign(_req("agent-b")))
        assert claims.agent_id == "agent-b"

    def test_unknown_key_id_rejected(self, tmp_path):
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        registry = AgentKeyRegistry()
        # Register only agent-a; signer with "key-unknown" is not in registry
        _, unknown_pub = generate_keypair()
        registry.register("agent-a", "key-a", pub_a)
        verifier, _ = _make_verifier(tmp_path, registry)
        priv_x, _ = generate_keypair()
        token_unknown = _forge_token(priv_x, "key-unknown", "agent-x")
        with pytest.raises(UnknownKeyIdError):
            verifier.verify(token_unknown)

    def test_no_kid_in_token_rejected(self, tmp_path):
        """Token without kid header (issued by core issue_token) is rejected in multi-agent mode."""
        from core.token_issuer import issue_token, TokenRequest
        private_key, public_key = generate_keypair()
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", public_key)
        verifier, _ = _make_verifier(tmp_path, registry)
        req = TokenRequest(
            agent_id="agent-a",
            destination_url=MERCHANT_URL,
            amount_requested=0.001,
            purpose="no-kid test",
            expires_in_seconds=60,
        )
        # issue_token does not include kid
        issued = issue_token(req, private_key)
        from core.token_verifier import InvalidPayloadError
        with pytest.raises(InvalidPayloadError, match="Missing kid"):
            verifier.verify(issued.token)


# ---------------------------------------------------------------------------
# Class 4: Audit log signer events
# ---------------------------------------------------------------------------

class TestAuditLogSignerEvents:
    """Verify signer_verified and signer_rejected records are written correctly."""

    def test_successful_verify_writes_signer_verified(self, tmp_path):
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", pub_a)
        verifier, audit_log = _make_verifier(tmp_path, registry)
        verifier.verify(signer_a.sign(_req("agent-a")))
        events = audit_log.read_all()
        verified = [e for e in events if e["event_type"] == "signer_verified"]
        assert len(verified) == 1
        assert verified[0]["agent_id"] == "agent-a"
        assert verified[0]["key_id"] == "key-a"

    def test_signer_verified_contains_jti(self, tmp_path):
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", pub_a)
        verifier, audit_log = _make_verifier(tmp_path, registry)
        verifier.verify(signer_a.sign(_req("agent-a")))
        events = audit_log.read_all()
        verified = [e for e in events if e["event_type"] == "signer_verified"]
        assert verified[0]["jti"] is not None

    def test_compromised_key_writes_signer_rejected(self, tmp_path):
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", pub_a)
        registry.mark_compromised("key-a")
        verifier, audit_log = _make_verifier(tmp_path, registry)
        with pytest.raises(CompromisedKeyError):
            verifier.verify(signer_a.sign(_req("agent-a")))
        events = audit_log.read_all()
        rejected = [e for e in events if e["event_type"] == "signer_rejected"]
        assert len(rejected) == 1
        assert rejected[0]["reason"] == "signer_compromised"
        assert rejected[0]["key_id"] == "key-a"

    def test_signer_mismatch_writes_signer_rejected(self, tmp_path):
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        priv_b, pub_b = generate_keypair()
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", pub_a)
        registry.register("agent-b", "key-b", pub_b)
        verifier, audit_log = _make_verifier(tmp_path, registry)
        forged = _forge_token(priv_b, "key-b", "agent-a")
        with pytest.raises(SignerMismatchError):
            verifier.verify(forged)
        events = audit_log.read_all()
        rejected = [e for e in events if e["event_type"] == "signer_rejected"]
        assert len(rejected) == 1
        assert rejected[0]["reason"] == "signer_mismatch"
        assert rejected[0]["signature_verified"] is True

    def test_signer_rejected_has_status_rejected(self, tmp_path):
        signer_a, pub_a = _make_signer("agent-a", "key-a")
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a", pub_a)
        registry.mark_compromised("key-a")
        verifier, audit_log = _make_verifier(tmp_path, registry)
        with pytest.raises(CompromisedKeyError):
            verifier.verify(signer_a.sign(_req("agent-a")))
        events = audit_log.read_all()
        rejected = [e for e in events if e["event_type"] == "signer_rejected"]
        assert rejected[0]["status"] == "rejected"

    def test_audit_log_make_signer_verified_record_fields(self):
        record = AuditLog.make_signer_verified_record(
            agent_id="agent-a", key_id="key-a-001", jti="jti-xyz", nonce="n-001"
        )
        assert record["event_type"] == "signer_verified"
        assert record["signer_status"] == "active"
        assert record["signature_verified"] is True
        assert record["status"] == "approved"
        assert "event_id" in record
        assert "timestamp" in record

    def test_audit_log_make_signer_rejected_record_fields(self):
        record = AuditLog.make_signer_rejected_record(
            key_id="key-a", reason="signer_mismatch", nonce="n-001",
            signer_status="active", signature_verified=True,
            agent_id="agent-a", jti="jti-xyz",
        )
        assert record["event_type"] == "signer_rejected"
        assert record["reason"] == "signer_mismatch"
        assert record["signature_verified"] is True
        assert record["status"] == "rejected"
