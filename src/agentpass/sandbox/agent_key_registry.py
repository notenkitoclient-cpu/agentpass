"""
EXP-005c: Agent keypair registry.

Maps key_id → (agent_id, public_key, status) to support multi-agent
verification where each agent owns a distinct signing keypair.

Responsibilities (bounded):
  - Register agent keypairs by key_id
  - Resolve key_id → (owner_agent_id, public_key)
  - Mark a key as compromised
  - Report key status

Does NOT: sign tokens, verify JWTs, write audit logs, or manage secrets.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .errors import CompromisedKeyError, UnknownKeyIdError


@dataclass(frozen=True)
class _KeyEntry:
    agent_id: str
    public_key: Ed25519PublicKey
    status: str  # "active" | "compromised"


class AgentKeyRegistry:
    """
    In-memory mapping from key_id to (agent_id, Ed25519PublicKey, status).

    Each key_id must be globally unique across all agents. An agent may hold
    multiple key_ids (key rotation), but each key_id belongs to exactly one agent.

    Usage:
        registry = AgentKeyRegistry()
        registry.register("agent-a", "key-a-001", agent_a_public_key)
        owner_id, pub_key = registry.resolve("key-a-001")
        registry.mark_compromised("key-a-001")
    """

    def __init__(self) -> None:
        self._keys: dict[str, _KeyEntry] = {}

    def register(
        self,
        agent_id: str,
        key_id: str,
        public_key: Ed25519PublicKey,
    ) -> None:
        """Register a public key for an agent. Overwrites any prior entry for key_id."""
        self._keys[key_id] = _KeyEntry(
            agent_id=agent_id,
            public_key=public_key,
            status="active",
        )

    def resolve(self, key_id: str) -> tuple[str, Ed25519PublicKey]:
        """
        Return (owner_agent_id, public_key) for the given key_id.

        Raises:
            UnknownKeyIdError     — key_id is not registered
            CompromisedKeyError   — key is registered but marked compromised
        """
        entry = self._keys.get(key_id)
        if entry is None:
            raise UnknownKeyIdError(f"Unknown key_id: {key_id!r}", key_id=key_id)
        if entry.status == "compromised":
            raise CompromisedKeyError(f"Key {key_id!r} is compromised", key_id=key_id)
        return entry.agent_id, entry.public_key

    def mark_compromised(self, key_id: str) -> None:
        """
        Mark a key as compromised. All subsequent resolve() calls will raise.

        Raises:
            UnknownKeyIdError — key_id is not registered
        """
        entry = self._keys.get(key_id)
        if entry is None:
            raise UnknownKeyIdError(f"Unknown key_id: {key_id!r}", key_id=key_id)
        self._keys[key_id] = _KeyEntry(
            agent_id=entry.agent_id,
            public_key=entry.public_key,
            status="compromised",
        )

    def key_status(self, key_id: str) -> str:
        """
        Return "active" or "compromised".

        Raises:
            UnknownKeyIdError — key_id is not registered
        """
        entry = self._keys.get(key_id)
        if entry is None:
            raise UnknownKeyIdError(f"Unknown key_id: {key_id!r}", key_id=key_id)
        return entry.status
