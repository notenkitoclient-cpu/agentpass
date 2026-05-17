"""
EXP-005a: Append-only JSONL audit log for sandbox experiments.

Design constraints:
  - Append-only: existing entries are never modified or deleted
  - Each line is a self-contained JSON object (JSONL format)
  - read_all() enables replay validation — any budget_exceeded event
    can be reconstructed and re-verified against SandboxBudgetControl
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Fields that every budget_exceeded record must contain.
REQUIRED_FIELDS: frozenset[str] = frozenset({
    "event_id",
    "event_type",
    "timestamp",
    "agent_id",
    "amount",
    "budget_limit",
    "nonce",
    "status",
    "reason",
})


class AuditLog:
    """
    Append-only JSONL audit log.

    Usage:
        log = AuditLog(Path("audit_exp005a.jsonl"))
        record = log.make_budget_exceeded_record(
            agent_id="agent-001", amount=0.002,
            budget_limit=0.001, nonce=str(uuid.uuid4()),
        )
        log.append(record)
        all_events = log.read_all()
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, record: dict) -> None:
        """Append one record as a JSONL line. Creates the file if absent."""
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_all(self) -> list[dict]:
        """
        Return all records as a list of dicts.
        Returns [] if the file does not exist or is empty.
        """
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    # ------------------------------------------------------------------
    # Record factories
    # ------------------------------------------------------------------

    @staticmethod
    def make_budget_exceeded_record(
        *,
        agent_id: str,
        amount: float,
        budget_limit: float,
        nonce: str,
    ) -> dict:
        """
        Build a budget_exceeded audit record with all required fields.

        The returned dict satisfies REQUIRED_FIELDS and can be passed
        directly to append(). All fields needed for replay validation
        (amount, budget_limit) are included.
        """
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "budget_exceeded",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "agent_id": agent_id,
            "amount": amount,
            "budget_limit": budget_limit,
            "nonce": nonce,
            "status": "rejected",
            "reason": "budget_exceeded",
        }

    @staticmethod
    def make_purchase_approved_record(
        *,
        agent_id: str,
        amount: float,
        token_id: str,
        nonce: str,
    ) -> dict:
        """Build a purchase_approved audit record (EXP-005b)."""
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "purchase_approved",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "agent_id": agent_id,
            "amount": amount,
            "token_id": token_id,
            "nonce": nonce,
            "status": "approved",
        }

    @staticmethod
    def make_replay_detected_record(
        *,
        agent_id: str,
        token_id: str,
        nonce: str,
    ) -> dict:
        """Build a replay_detected audit record (EXP-005b)."""
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "replay_detected",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "agent_id": agent_id,
            "token_id": token_id,
            "nonce": nonce,
            "status": "rejected",
            "reason": "replay_detected",
        }

    @staticmethod
    def make_spending_frozen_record(
        *,
        burst_count: int,
        nonce: str,
    ) -> dict:
        """Build a spending_frozen audit record (EXP-006)."""
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "spending_frozen",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "burst_count": burst_count,
            "nonce": nonce,
            "status": "frozen",
            "reason": "replay_burst_detected",
        }

    @staticmethod
    def make_signer_verified_record(
        *,
        agent_id: str,
        key_id: str,
        jti: str,
        nonce: str,
    ) -> dict:
        """Build a signer_verified audit record (EXP-005c)."""
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "signer_verified",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "agent_id": agent_id,
            "key_id": key_id,
            "jti": jti,
            "signer_status": "active",
            "signature_verified": True,
            "nonce": nonce,
            "status": "approved",
        }

    @staticmethod
    def make_signer_rejected_record(
        *,
        key_id: str,
        reason: str,
        nonce: str,
        signer_status: str = "unknown",
        signature_verified: bool = False,
        agent_id: str | None = None,
        jti: str | None = None,
    ) -> dict:
        """
        Build a signer_rejected audit record (EXP-005c).

        reason values:
          "signer_compromised" — key is marked compromised
          "unknown_key_id"     — kid not in registry
          "signer_mismatch"    — sub ≠ key owner (signature valid, identity forged)
        """
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": "signer_rejected",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "agent_id": agent_id,
            "key_id": key_id,
            "jti": jti,
            "reason": reason,
            "signer_status": signer_status,
            "signature_verified": signature_verified,
            "nonce": nonce,
            "status": "rejected",
        }
