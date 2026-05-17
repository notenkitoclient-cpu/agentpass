"""
AgentPass Identity — 決定論的エージェントID派生

Ed25519 公開鍵（32 バイト）の SHA-256 ハッシュから UUID を決定論的に生成する。
同じ公開鍵からは常に同じ UUID が返る。
"""

from __future__ import annotations

import hashlib
import uuid


def derive_agent_id(public_key_bytes: bytes) -> str:
    """
    Ed25519 公開鍵バイト列から決定論的 UUID を生成する。

    Args:
        public_key_bytes: Ed25519 公開鍵の生バイト列（32 バイト）

    Returns:
        ハイフン区切り形式の UUID 文字列（例: "550e8400-e29b-41d4-a716-446655440000"）
    """
    digest = hashlib.sha256(public_key_bytes).digest()
    return str(uuid.UUID(bytes=digest[:16]))
