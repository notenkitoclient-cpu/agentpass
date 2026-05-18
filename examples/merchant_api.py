"""
AgentPass Demo Merchant API

FastAPI server demonstrating how to protect an endpoint with AgentPass tokens.

  GET /.well-known/agentpass.json  — public key discovery for agents
  GET /health                      — docker healthcheck
  GET /v1/pay                      — protected endpoint with replay defense

On first startup the merchant generates an Ed25519 keypair and saves it to
KEYS_FILE (default: examples/keys/demo_keys.json).  agent_client.py reads
the matching private key from that same file.

MERCHANT_AUD is an https:// URI as required by TokenRequest even though the
local transport uses plain HTTP.  In production both would be HTTPS.

Usage (local, two terminals):
  pip install agentpass-ai uvicorn
  python examples/merchant_api.py        # terminal 1
  python examples/agent_client.py        # terminal 2

Usage (Docker):
  cd examples && docker compose up
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Support running directly from repo without pip install -e .
_root = Path(__file__).resolve().parent.parent
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse

from agentpass import AnomalyDetector, VerificationError, generate_keypair, verify_token

# ---------------------------------------------------------------------------
# Configuration (all overridable via environment variables)
# ---------------------------------------------------------------------------

MERCHANT_ID = "demo-merchant-001"
AGENTPASS_VERSION = "1.0.0"

# Canonical HTTPS URL embedded in JWT aud claim.
# TokenRequest requires https:// — transport layer is separate.
MERCHANT_AUD = os.getenv("MERCHANT_AUD", "https://agentpass-demo.local/v1/pay")

KEYS_FILE = Path(os.getenv("KEYS_FILE", Path(__file__).parent / "keys" / "demo_keys.json"))

HOST = os.getenv("MERCHANT_HOST", "0.0.0.0")
PORT = int(os.getenv("MERCHANT_PORT", "8000"))

# ---------------------------------------------------------------------------
# Keypair bootstrap
# ---------------------------------------------------------------------------

def _load_or_create_keys() -> tuple[object, str]:
    """Load keypair from disk or generate a new one on first startup."""
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)

    if KEYS_FILE.exists():
        data = json.loads(KEYS_FILE.read_text())
        private_key = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(data["private_key_hex"])
        )
        print(f"[merchant] Loaded keypair from {KEYS_FILE}")
    else:
        private_key, _ = generate_keypair()
        priv_raw = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        pub_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        KEYS_FILE.write_text(
            json.dumps(
                {"private_key_hex": priv_raw.hex(), "public_key_hex": pub_raw.hex()},
                indent=2,
            )
        )
        print(f"[merchant] Generated new keypair → {KEYS_FILE}")
        print("[merchant] NOTE: demo_keys.json contains a private key (demo only, gitignored).")

    public_key = private_key.public_key()
    pub_hex = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return public_key, pub_hex


_public_key, _public_key_hex = _load_or_create_keys()
_detector = AnomalyDetector()

_AGENTPASS_JSON = {
    "agentpass_version": AGENTPASS_VERSION,
    "merchant_id": MERCHANT_ID,
    "public_key": _public_key_hex,
    "pricing": [{"endpoint": "/v1/pay", "price_per_token": 0.001}],
}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="AgentPass Demo Merchant", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/.well-known/agentpass.json")
async def agentpass_metadata():
    """Agents discover the merchant's registered public key here."""
    return _AGENTPASS_JSON


@app.get("/v1/pay")
async def pay(request: Request):
    """
    Protected endpoint. Requires:
      Authorization: AgentPass <token>

    Returns:
      200 — access granted, agent claims echoed back
      401 — missing or malformed token / expired
      403 — replay attack detected or destination mismatch
      400 — invalid token payload
    """
    auth = request.headers.get("Authorization", "")

    if not auth.startswith("AgentPass "):
        return JSONResponse(
            {
                "error_code": "INVALID_PAYLOAD",
                "detail": "Expected: Authorization: AgentPass <token>",
            },
            status_code=401,
        )

    token = auth[len("AgentPass "):]

    try:
        claims = verify_token(token, _public_key, MERCHANT_AUD)
    except VerificationError as exc:
        return JSONResponse(
            {"error_code": exc.error_code, "detail": str(exc)},
            status_code=exc.http_status,
        )

    if _detector.is_replay_attack(claims.token_id, claims.expires_at):
        return JSONResponse(
            {
                "error_code": "REPLAY_ATTACK",
                "detail": "Token already used — replay attack blocked.",
                "token_id": claims.token_id,
            },
            status_code=403,
        )

    print(
        f"[merchant] GRANTED  agent={claims.agent_id}"
        f"  amount={claims.amount} {claims.currency}"
        f"  jti={claims.token_id[:8]}..."
    )
    return {
        "status": "ok",
        "agent_id": claims.agent_id,
        "amount": claims.amount,
        "currency": claims.currency,
        "token_id": claims.token_id,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print()
    print("=" * 62)
    print("  AgentPass Demo Merchant")
    print("=" * 62)
    print(f"  Listening    : http://{HOST}:{PORT}")
    print(f"  MERCHANT_AUD : {MERCHANT_AUD}")
    print(f"  Public key   : {_public_key_hex[:24]}...")
    print(f"  Keys file    : {KEYS_FILE}")
    print()
    print("  Endpoints:")
    print("    GET /.well-known/agentpass.json")
    print("    GET /health")
    print("    GET /v1/pay  (Authorization: AgentPass <token>)")
    print("=" * 62)
    print()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
