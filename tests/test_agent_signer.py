"""
src/identity/agent_signer.py のテスト

derive_agent_id() の決定論性・一意性を検証する。
"""

from __future__ import annotations

import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.identity.agent_signer import derive_agent_id


def _make_key_bytes() -> bytes:
    return Ed25519PrivateKey.generate().public_key().public_bytes_raw()


# ---------------------------------------------------------------------------
# UUID 形式の正当性
# ---------------------------------------------------------------------------

class TestUuidFormat:
    def test_returns_valid_uuid_string(self):
        result = derive_agent_id(_make_key_bytes())
        uuid.UUID(result)  # 不正形式なら ValueError

    def test_uuid_has_hyphen_format(self):
        result = derive_agent_id(_make_key_bytes())
        assert result.count("-") == 4

    def test_uuid_total_length_is_36(self):
        result = derive_agent_id(_make_key_bytes())
        assert len(result) == 36


# ---------------------------------------------------------------------------
# 決定論性（同一入力 → 同一出力）
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_key_returns_same_uuid(self):
        key_bytes = _make_key_bytes()
        assert derive_agent_id(key_bytes) == derive_agent_id(key_bytes)

    def test_deterministic_across_five_calls(self):
        key_bytes = _make_key_bytes()
        results = {derive_agent_id(key_bytes) for _ in range(5)}
        assert len(results) == 1

    def test_same_raw_bytes_produce_same_uuid(self):
        raw = b"\x00" * 32  # 定数入力
        assert derive_agent_id(raw) == derive_agent_id(raw)


# ---------------------------------------------------------------------------
# 一意性（異なる入力 → 異なる出力）
# ---------------------------------------------------------------------------

class TestUniqueness:
    def test_different_keys_return_different_uuids(self):
        key1 = _make_key_bytes()
        key2 = _make_key_bytes()
        assert derive_agent_id(key1) != derive_agent_id(key2)

    def test_three_different_keys_all_unique(self):
        keys = [_make_key_bytes() for _ in range(3)]
        ids = [derive_agent_id(k) for k in keys]
        assert len(set(ids)) == 3

    def test_all_zeros_and_all_ones_differ(self):
        zeros = b"\x00" * 32
        ones  = b"\xff" * 32
        assert derive_agent_id(zeros) != derive_agent_id(ones)
