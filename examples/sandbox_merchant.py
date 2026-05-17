"""
EXP-004: Minimal AgentPass Sandbox Merchant

Endpoints:
  GET /.well-known/agentpass.json  — merchant metadata (for AgentPassCrawler)
  GET /api/data                    — JWT verify + replay guard → 200 or 401

On first run, generates an Ed25519 keypair and saves it to
examples/sandbox_keys.json.  sandbox_agent.py loads the private key from
that file to sign tokens.

WARNING: sandbox_keys.json contains raw private key bytes.
         Add  examples/sandbox_keys.json  to .gitignore before committing.

MERCHANT_URL used as the JWT `aud` claim:
  https://sandbox.agentpass.local/api/data
  (TokenRequest requires https://; transport is plain HTTP for local sandbox)

Usage:
  python examples/sandbox_merchant.py          # http://127.0.0.1:8080
  python examples/sandbox_merchant.py --port 9090
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Allow running as `python examples/sandbox_merchant.py` without `pip install -e .`
# Mirrors pytest's `pythonpath = ["src", "."]` from pyproject.toml:
#   src/  → enables `from core.xxx import`
#   .     → enables `from src.core.xxx import` (used inside authorization_middleware)
_proj = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_proj / "src"))
sys.path.insert(0, str(_proj))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from core.anomaly_detector import AnomalyDetector
from core.token_issuer import generate_keypair
from core.token_verifier import (
    DestinationMismatchError,
    InvalidPayloadError,
    TokenExpiredError,
    verify_token,
)

# ---------------------------------------------------------------------------
# Sandbox configuration
# ---------------------------------------------------------------------------

MERCHANT_ID = "sandbox-merchant-001"
AGENTPASS_VERSION = "1.0.0"

# HTTPS URI satisfies TokenRequest.destination_url validation.
# The server itself runs on plain HTTP locally — the string only appears in
# the JWT `aud` claim and the verify_token() audience check.
MERCHANT_URL = "https://sandbox.agentpass.local/api/data"

KEYS_FILE = Path(__file__).parent / "sandbox_keys.json"

# ---------------------------------------------------------------------------
# Keypair bootstrap  (generated once, persisted across restarts)
# ---------------------------------------------------------------------------

def _load_or_create_keys() -> tuple[Ed25519PrivateKey, object, str]:
    if KEYS_FILE.exists():
        data = json.loads(KEYS_FILE.read_text())
        private_key = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(data["private_key_hex"])
        )
        print(f"[merchant] Loaded keypair from {KEYS_FILE.name}")
    else:
        private_key, _ = generate_keypair()
        priv_raw = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        pub_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        KEYS_FILE.write_text(json.dumps({
            "private_key_hex": priv_raw.hex(),
            "public_key_hex": pub_raw.hex(),
        }, indent=2))
        print(f"[merchant] Generated new keypair → {KEYS_FILE.name}")
        print(f"[merchant] !! Add {KEYS_FILE.name} to .gitignore — contains private key !!")

    public_key = private_key.public_key()
    pub_hex = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return private_key, public_key, pub_hex


_private_key, _public_key, _public_key_hex = _load_or_create_keys()

# Replay detector — module-level singleton; persists for the server lifetime
_detector = AnomalyDetector()

# Build metadata response once at import time
_METADATA_BYTES = json.dumps({
    "agentpass_version": AGENTPASS_VERSION,
    "merchant_id": MERCHANT_ID,
    "public_key": _public_key_hex,
    "pricing": [{"endpoint": "/api/data", "price_per_token": 0.001}],
}).encode()

# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class _MerchantHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/.well-known/agentpass.json":
            self._send_bytes(200, _METADATA_BYTES)
        elif self.path == "/api/data":
            self._handle_api_data()
        else:
            self._send_json(404, {"error": "Not found"})

    def _handle_api_data(self) -> None:
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_json(401, {"error": "Missing Bearer token"})
            return

        token = auth_header[len("Bearer "):]

        try:
            claims = verify_token(token, _public_key, MERCHANT_URL)
        except TokenExpiredError as exc:
            self._send_json(401, {"error": str(exc)})
            return
        except DestinationMismatchError as exc:
            self._send_json(403, {"error": str(exc)})
            return
        except InvalidPayloadError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        if _detector.is_replay_attack(claims.token_id, claims.expires_at):
            self._send_json(
                401,
                {
                    "error": "Replay attack detected: token already used",
                    "token_id": claims.token_id,
                },
            )
            return

        self._send_json(200, {
            "message": "Access granted",
            "agent_id": claims.agent_id,
            "amount_charged": claims.amount,
            "currency": claims.currency,
            "token_id": claims.token_id,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _send_json(self, status: int, body: dict) -> None:
        self._send_bytes(status, json.dumps(body).encode())

    def _send_bytes(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        status = args[1] if len(args) > 1 else "?"
        print(f"[merchant] {self.command} {self.path} → {status}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AgentPass Sandbox Merchant — EXP-004"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=8080, help="Bind port")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  AgentPass Sandbox Merchant  [EXP-004]")
    print("=" * 60)
    print(f"  Listening : http://{args.host}:{args.port}")
    print(f"  MERCHANT_URL (aud claim) : {MERCHANT_URL}")
    print(f"  Public key  : {_public_key_hex[:24]}...")
    print(f"  Keys file   : {KEYS_FILE}")
    print()
    print("  Endpoints:")
    print("    GET /.well-known/agentpass.json")
    print("    GET /api/data  (Authorization: Bearer <JWT>)")
    print("=" * 60)
    print()

    server = HTTPServer((args.host, args.port), _MerchantHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[merchant] Shutting down.")


if __name__ == "__main__":
    main()
