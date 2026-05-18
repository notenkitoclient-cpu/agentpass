"""
AgentPass Demo Agent Client

Demonstrates the full replay-safe authentication flow:

  Step 1  Fetch merchant metadata → confirm registered public key
  Step 2  Load agent private key from demo_keys.json
  Step 3  Issue one-time JWT via issue_token()
  Step 4  Call /v1/pay (attempt 1) → expect 200 OK
  Step 5  Replay same token      → expect 403 REPLAY_ATTACK  ← replay safe!
  Step 6  Issue fresh token      → expect 200 OK

Prerequisites:
  python examples/merchant_api.py     # terminal 1 (must be running)
  python examples/agent_client.py     # terminal 2

Or with Docker:
  cd examples && docker compose up

Exit codes:
  0 — all steps passed
  1 — any step failed
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Support running directly from repo without pip install -e .
_root = Path(__file__).resolve().parent.parent
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agentpass import MerchantMetadata, TokenRequest, issue_token

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Must match MERCHANT_AUD in merchant_api.py — used as JWT aud claim.
# TokenRequest requires https:// even when local transport is plain HTTP.
MERCHANT_AUD = os.getenv("MERCHANT_AUD", "https://agentpass-demo.local/v1/pay")

_host = os.getenv("MERCHANT_HOST", "127.0.0.1")
_port = os.getenv("MERCHANT_PORT", "8000")
MERCHANT_BASE = f"http://{_host}:{_port}"

KEYS_FILE = Path(os.getenv("KEYS_FILE", Path(__file__).parent / "keys" / "demo_keys.json"))

AGENT_ID = "demo-agent-001"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_metadata() -> MerchantMetadata:
    """
    Fetch agentpass.json directly via httpx.
    AgentPassCrawler is intentionally bypassed — its SSRF guard blocks
    localhost (correct in production, incompatible with a local demo).
    """
    url = f"{MERCHANT_BASE}/.well-known/agentpass.json"
    try:
        r = httpx.get(url, timeout=10.0)
        r.raise_for_status()
    except httpx.ConnectError:
        print(f"[agent] ERROR: Cannot connect to {MERCHANT_BASE}")
        print("[agent]        Is merchant_api.py running?")
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        print(f"[agent] ERROR: Metadata fetch failed — {exc}")
        sys.exit(1)
    return MerchantMetadata.model_validate(r.json())


def _wait_for_keys(max_wait: int = 30) -> None:
    """Wait for merchant to write the keypair file (handles Docker startup ordering)."""
    deadline = time.monotonic() + max_wait
    while not KEYS_FILE.exists():
        if time.monotonic() > deadline:
            print(f"[agent] ERROR: {KEYS_FILE} not found after {max_wait}s.")
            print("[agent]        Is merchant_api.py running?")
            sys.exit(1)
        time.sleep(1)


def _load_private_key() -> Ed25519PrivateKey:
    _wait_for_keys()
    data = json.loads(KEYS_FILE.read_text())
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(data["private_key_hex"]))


def _call(token: str) -> httpx.Response:
    return httpx.get(
        f"{MERCHANT_BASE}/v1/pay",
        headers={"Authorization": f"AgentPass {token}"},
        timeout=10.0,
    )


# ---------------------------------------------------------------------------
# Demo flow
# ---------------------------------------------------------------------------

def main() -> None:
    print()
    print("=" * 62)
    print("  AgentPass Demo — replay-safe agent authentication")
    print("=" * 62)

    # Step 1: Fetch merchant metadata
    print("\n[Step 1] Fetching merchant metadata...")
    metadata = _fetch_metadata()
    pricing = metadata.pricing[0]
    print(f"  merchant_id : {metadata.merchant_id}")
    print(f"  public_key  : {metadata.public_key[:24]}...")
    print(f"  pricing     : {pricing.price_per_token} JPY  →  {pricing.endpoint}")

    # Step 2: Load agent private key
    print("\n[Step 2] Loading agent private key from demo_keys.json...")
    private_key = _load_private_key()
    pub_hex = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    key_match = pub_hex == metadata.public_key
    print(f"  Agent public key     : {pub_hex[:24]}...")
    print(f"  Matches merchant key : {'✓ yes' if key_match else '✗ MISMATCH'}")
    if not key_match:
        print("[agent] ABORT: Public key mismatch — delete examples/keys/ and restart.")
        sys.exit(1)

    # Step 3: Issue one-time token
    print("\n[Step 3] Issuing one-time JWT via issue_token()...")
    req = TokenRequest(
        agent_id=AGENT_ID,
        destination_url=MERCHANT_AUD,
        amount_requested=pricing.price_per_token,
        purpose="demo data access",
        expires_in_seconds=60,
    )
    issued = issue_token(req, private_key)
    print(f"  token_id    : {issued.token_id}")
    print(f"  valid_until : {issued.valid_until.strftime('%H:%M:%SZ')} UTC")
    print(f"  amount      : {issued.max_amount} JPY")
    print(f"  aud         : {issued.destination_url}")

    # Step 4: First request — expect 200
    print("\n[Step 4] Attempt 1 — first call with valid token (expect 200)...")
    r1 = _call(issued.token)
    b1 = r1.json()
    ok1 = r1.status_code == 200
    print(f"  {'✓' if ok1 else '✗'} HTTP {r1.status_code}: {b1}")
    if not ok1:
        print("[agent] ABORT: First call failed — token flow broken.")
        sys.exit(1)

    # Step 5: Replay same token — expect 403
    print("\n[Step 5] Attempt 2 — replaying the same token (expect 403 REPLAY_ATTACK)...")
    r2 = _call(issued.token)
    b2 = r2.json()
    replay_blocked = r2.status_code == 403 and b2.get("error_code") == "REPLAY_ATTACK"
    print(f"  {'✓' if replay_blocked else '✗'} HTTP {r2.status_code}: {b2}")
    if not replay_blocked:
        print("[agent] ABORT: Replay attack was NOT blocked — security failure!")
        sys.exit(1)

    # Step 6: Fresh token — expect 200
    print("\n[Step 6] Attempt 3 — issuing a fresh token (new JTI, expect 200)...")
    issued2 = issue_token(req, private_key)
    r3 = _call(issued2.token)
    b3 = r3.json()
    ok3 = r3.status_code == 200
    print(f"  {'✓' if ok3 else '✗'} HTTP {r3.status_code}: {b3}")
    if not ok3:
        print("[agent] ABORT: Fresh token was unexpectedly rejected.")
        sys.exit(1)

    # Summary
    print()
    print("=" * 62)
    print("  DEMO RESULT: ALL STEPS PASSED")
    print()
    print("  ✓ Step 1  Merchant metadata fetched")
    print("  ✓ Step 2  Agent private key loaded — public key matched")
    print("  ✓ Step 3  One-time JWT issued (Ed25519 signed)")
    print("  ✓ Step 4  First call granted   (HTTP 200)")
    print("  ✓ Step 5  Replay blocked       (HTTP 403 REPLAY_ATTACK)")
    print("  ✓ Step 6  Fresh token granted  (HTTP 200)")
    print()
    print("  AgentPass is replay-safe: each token can only be used once.")
    print("=" * 62)
    print()


if __name__ == "__main__":
    main()
