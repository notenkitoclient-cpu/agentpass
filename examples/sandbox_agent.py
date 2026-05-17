"""
EXP-004: Minimal AgentPass Sandbox Agent

Runs the agent side of the EXP-004 purchase flow against a running
sandbox_merchant.py instance:

  Step 1: Fetch merchant metadata (httpx direct — bypasses AgentPassCrawler
          SSRF check which intentionally blocks localhost)
  Step 2: Load agent private key from sandbox_keys.json
  Step 3: Issue a one-time JWT token via issue_token()
  Step 4: GET /api/data (1st attempt) → expect 200 Access granted
  Step 5: GET /api/data (2nd attempt, same token) → expect 401 Replay rejected
  Step 6: Save both results to examples/audit_exp004.jsonl (JSONL)

Prerequisites:
  python examples/sandbox_merchant.py     # terminal 1 (must be running)
  python examples/sandbox_agent.py        # terminal 2

Exit codes:
  0 — all steps passed (both success criteria met)
  1 — any step failed (merchant unreachable / token verify failed / replay not blocked)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Mirrors pytest's `pythonpath = ["src", "."]` from pyproject.toml.
# Required for `from core.xxx import` and for `from src.core.xxx import`
# (used transitively by core/__init__.py → authorization_middleware.py).
_proj = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_proj / "src"))
sys.path.insert(0, str(_proj))

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from core.agentpass_crawler import MerchantMetadata
from core.token_issuer import TokenRequest, issue_token

# ---------------------------------------------------------------------------
# Sandbox configuration
# ---------------------------------------------------------------------------

MERCHANT_BASE = "http://127.0.0.1:8080"
METADATA_URL = f"{MERCHANT_BASE}/.well-known/agentpass.json"
DATA_URL = f"{MERCHANT_BASE}/api/data"

# Must match sandbox_merchant.MERCHANT_URL — used as JWT `aud` claim.
# TokenRequest requires https:// even though transport is plain HTTP locally.
MERCHANT_AUD = "https://sandbox.agentpass.local/api/data"

AGENT_ID = "sandbox-agent-001"
KEYS_FILE = Path(__file__).parent / "sandbox_keys.json"
AUDIT_FILE = Path(__file__).parent / "audit_exp004.jsonl"

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(record: dict) -> None:
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _fetch_metadata() -> MerchantMetadata:
    """
    Fetch agentpass.json directly via httpx.
    AgentPassCrawler is intentionally bypassed — its SSRF guard blocks
    localhost (127.0.0.1 is a loopback address), which is correct in
    production but incompatible with a local sandbox.
    """
    try:
        r = httpx.get(METADATA_URL, timeout=5.0)
        r.raise_for_status()
    except httpx.ConnectError:
        print(f"[agent] ERROR: Cannot connect to {MERCHANT_BASE}")
        print("[agent]        Is sandbox_merchant.py running?")
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        print(f"[agent] ERROR: Metadata fetch failed — {exc}")
        sys.exit(1)
    return MerchantMetadata.model_validate(r.json())


def _load_private_key() -> Ed25519PrivateKey:
    if not KEYS_FILE.exists():
        print(f"[agent] ERROR: {KEYS_FILE.name} not found.")
        print("[agent]        sandbox_merchant.py generates this file on first run.")
        sys.exit(1)
    data = json.loads(KEYS_FILE.read_text())
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(data["private_key_hex"]))


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def main() -> None:
    # Reset audit log so each run starts clean
    AUDIT_FILE.unlink(missing_ok=True)

    print()
    print("=" * 62)
    print("  AgentPass Sandbox Agent  [EXP-004]")
    print("=" * 62)

    # ------------------------------------------------------------------
    # Step 1: Fetch merchant metadata
    # ------------------------------------------------------------------
    print("\n[Step 1] Fetching merchant metadata from sandbox_merchant...")
    metadata = _fetch_metadata()
    pricing = metadata.pricing[0]
    print(f"  merchant_id : {metadata.merchant_id}")
    print(f"  public_key  : {metadata.public_key[:24]}...")
    print(f"  pricing     : {pricing.price_per_token} JPY per call to {pricing.endpoint}")

    # ------------------------------------------------------------------
    # Step 2: Load agent private key
    # ------------------------------------------------------------------
    print("\n[Step 2] Loading agent private key from sandbox_keys.json...")
    private_key = _load_private_key()
    pub_hex = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    print(f"  Agent public key : {pub_hex[:24]}...")
    print(f"  Sandbox keypair matches merchant's public_key: {pub_hex == metadata.public_key}")

    # ------------------------------------------------------------------
    # Step 3: Issue one-time JWT token
    # ------------------------------------------------------------------
    print("\n[Step 3] Issuing one-time JWT token via issue_token()...")
    req = TokenRequest(
        agent_id=AGENT_ID,
        destination_url=MERCHANT_AUD,
        amount_requested=pricing.price_per_token,
        purpose="EXP-004 sandbox purchase",
        expires_in_seconds=60,
    )
    issued = issue_token(req, private_key)
    print(f"  token_id    : {issued.token_id}")
    print(f"  valid_until : {issued.valid_until.strftime('%H:%M:%SZ')} UTC")
    print(f"  amount      : {issued.max_amount} JPY")
    print(f"  destination : {issued.destination_url}")

    # ------------------------------------------------------------------
    # Step 4: First request — expect 200
    # ------------------------------------------------------------------
    print("\n[Step 4] Attempt 1 — first access with valid token (expect 200)...")
    r1 = httpx.get(DATA_URL, headers={"Authorization": f"Bearer {issued.token}"})
    body1 = r1.json()
    success1 = r1.status_code == 200

    _log({
        "attempt": 1,
        "status": "success" if success1 else "unexpected_failure",
        "http_status": r1.status_code,
        "jti": issued.token_id,
        "agent_id": AGENT_ID,
        "amount_jpy": issued.max_amount,
        "merchant_response": body1,
        "ts": _ts(),
    })

    if success1:
        print(f"  ✓ 200 OK — {body1.get('message')} (charged: {body1.get('amount_charged')} JPY)")
    else:
        print(f"  ✗ Unexpected {r1.status_code}: {body1}")
        print("[agent] ABORT: First access failed — token flow broken.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 5: Second request (same token) — expect 401 replay rejection
    # ------------------------------------------------------------------
    print("\n[Step 5] Attempt 2 — replay with same token (expect 401)...")
    r2 = httpx.get(DATA_URL, headers={"Authorization": f"Bearer {issued.token}"})
    body2 = r2.json()
    replay_blocked = r2.status_code == 401 and "Replay" in body2.get("error", "")

    _log({
        "attempt": 2,
        "status": "replay_rejected" if replay_blocked else "unexpected_success",
        "http_status": r2.status_code,
        "jti": issued.token_id,
        "merchant_response": body2,
        "ts": _ts(),
    })

    if replay_blocked:
        print(f"  ✓ 401 — {body2.get('error')}")
    else:
        print(f"  ✗ Unexpected {r2.status_code}: {body2}")
        print("[agent] ABORT: Replay attack was NOT blocked — security breach!")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 62)
    print("  EXP-004 RESULT: ALL CRITERIA MET")
    print()
    print("  ✓ Metadata fetched   (merchant_id, public_key, pricing)")
    print("  ✓ Token issued       (Ed25519 JWT, one-time use)")
    print("  ✓ Attempt 1 granted  (200 Access granted)")
    print("  ✓ Attempt 2 blocked  (401 Replay attack detected)")
    print(f"  ✓ Audit log saved  → {AUDIT_FILE.name}")
    print("=" * 62)

    # Print the audit log for visibility
    print()
    print(f"--- {AUDIT_FILE.name} ---")
    for line in AUDIT_FILE.read_text(encoding="utf-8").strip().splitlines():
        entry = json.loads(line)
        print(
            f"  attempt={entry['attempt']}"
            f"  status={entry['status']}"
            f"  http={entry['http_status']}"
            f"  jti={entry['jti'][:8]}..."
            f"  ts={entry['ts']}"
        )
    print("-" * 30)
    print()


if __name__ == "__main__":
    main()
