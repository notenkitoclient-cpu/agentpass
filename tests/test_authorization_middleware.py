"""
authorization_middleware の動作確認テスト

Starlette TestClient を使用し、外部通信ゼロで決定的に動作する。
base_url="https://merchant.example.com" に統一することで、
トークンの aud クレームと request.url を一致させる。
"""

from __future__ import annotations

import base64
import json
import time
import uuid

import jwt
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.core.token_issuer import TokenRequest, generate_keypair, issue_token
from src.merchant.agentpass_crawler import AgentPassConfig, PricingEntry
from src.merchant.authorization_middleware import AgentPassMiddleware

# ---------------------------------------------------------------------------
# テスト定数
# ---------------------------------------------------------------------------

BASE_URL = "https://merchant.example.com"
ENDPOINT = "/api/data"
MERCHANT_URL = f"{BASE_URL}{ENDPOINT}"

OTHER_URL = "https://attacker.example.com/steal"


# ---------------------------------------------------------------------------
# テスト用フィクスチャ・ユーティリティ
# ---------------------------------------------------------------------------

async def _ok_handler(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


@pytest.fixture(scope="module")
def keypair():
    return generate_keypair()


@pytest.fixture(scope="module")
def client(keypair):
    _, public_key = keypair
    inner = Starlette(routes=[Route(ENDPOINT, _ok_handler)])
    app = AgentPassMiddleware(inner, public_key=public_key)
    return TestClient(app, base_url=BASE_URL, raise_server_exceptions=True)


@pytest.fixture
def valid_token(keypair):
    """MERCHANT_URL 宛の有効なトークンを返す。"""
    private_key, _ = keypair
    req = TokenRequest(
        agent_id="agent-xyz",
        destination_url=MERCHANT_URL,
        amount_requested=0.001,
        purpose="fetch data",
    )
    return issue_token(req, private_key).token


def _auth(token: str) -> dict:
    return {"Authorization": f"AgentPass {token}"}


def _expired_token(private_key, aud: str) -> str:
    """秒単位で過去の exp を持つ期限切れトークンを生成する。"""
    now = int(time.time())
    payload = {
        "sub": "agent-xyz",
        "aud": aud,
        "iat": now - 120,
        "exp": now - 60,
        "jti": str(uuid.uuid4()),
        "amt": 0.001,
        "cur": "JPY",
        "agp": "1",
    }
    return jwt.encode(payload, private_key, algorithm="EdDSA")


def _tampered_token(valid_token: str) -> str:
    parts = valid_token.split(".")
    return parts[0] + "." + parts[1] + ".AAAA_badsig_ZZZZ"


def _make_agentpass_config(public_key) -> AgentPassConfig:
    """公開鍵を含む AgentPassConfig を組み立てる（from_agentpass_url テスト用）。"""
    raw = public_key.public_bytes_raw()
    b64_key = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return AgentPassConfig(
        agentpass_version="1.0",
        merchant_id=str(uuid.uuid4()),
        merchant_name="AgentPass Service",
        public_key=b64_key,
        accepted_currencies=["JPY"],
        pricing=[PricingEntry(endpoint="/token", price_per_request=0.001, currency="JPY")],
        settlement_address="settle-addr",
        min_agent_credit_score=0.0,
    )


# ---------------------------------------------------------------------------
# 正常系
# ---------------------------------------------------------------------------

class TestNormalCase:
    def test_valid_token_returns_200(self, client, valid_token):
        resp = client.get(ENDPOINT, headers=_auth(valid_token))
        assert resp.status_code == 200

    def test_downstream_handler_response_is_returned(self, client, valid_token):
        resp = client.get(ENDPOINT, headers=_auth(valid_token))
        assert resp.json() == {"ok": True}

    def test_each_unique_token_passes(self, client, keypair):
        """同じエージェントから2回別々のトークンを発行してどちらも通過する。"""
        private_key, _ = keypair
        req = TokenRequest(
            agent_id="agent-abc",
            destination_url=MERCHANT_URL,
            amount_requested=0.001,
            purpose="test",
        )
        token_a = issue_token(req, private_key).token
        token_b = issue_token(req, private_key).token

        assert client.get(ENDPOINT, headers=_auth(token_a)).status_code == 200
        assert client.get(ENDPOINT, headers=_auth(token_b)).status_code == 200


# ---------------------------------------------------------------------------
# 異常系 — Authorization ヘッダー検証
# ---------------------------------------------------------------------------

class TestHeaderValidation:
    def test_missing_header_returns_400(self, client):
        resp = client.get(ENDPOINT)
        assert resp.status_code == 400
        body = resp.json()
        assert body["error_code"] == "INVALID_PAYLOAD"
        assert body["http_status"] == 400

    def test_bearer_scheme_returns_400(self, client, valid_token):
        resp = client.get(ENDPOINT, headers={"Authorization": f"Bearer {valid_token}"})
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"

    def test_basic_scheme_returns_400(self, client):
        resp = client.get(ENDPOINT, headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 400

    def test_lowercase_scheme_returns_400(self, client, valid_token):
        """スキームは大文字小文字を区別する（"agentpass" は弾く）。"""
        resp = client.get(ENDPOINT, headers={"Authorization": f"agentpass {valid_token}"})
        assert resp.status_code == 400

    def test_token_only_no_scheme_returns_400(self, client, valid_token):
        resp = client.get(ENDPOINT, headers={"Authorization": valid_token})
        assert resp.status_code == 400

    def test_scheme_only_no_token_returns_400(self, client):
        resp = client.get(ENDPOINT, headers={"Authorization": "AgentPass"})
        assert resp.status_code == 400

    def test_scheme_with_whitespace_only_returns_400(self, client):
        resp = client.get(ENDPOINT, headers={"Authorization": "AgentPass   "})
        assert resp.status_code == 400

    def test_error_response_has_required_json_keys(self, client):
        resp = client.get(ENDPOINT)
        body = resp.json()
        assert "error_code" in body
        assert "message" in body
        assert "http_status" in body


# ---------------------------------------------------------------------------
# 異常系 — トークン検証失敗
# ---------------------------------------------------------------------------

class TestTokenValidation:
    def test_expired_token_returns_401(self, client, keypair):
        private_key, _ = keypair
        token = _expired_token(private_key, MERCHANT_URL)

        resp = client.get(ENDPOINT, headers=_auth(token))
        assert resp.status_code == 401
        body = resp.json()
        assert body["error_code"] == "TOKEN_EXPIRED"
        assert body["http_status"] == 401

    def test_wrong_destination_returns_403(self, client, keypair):
        """他の URL 宛に発行したトークンは弾かれる。"""
        private_key, _ = keypair
        req = TokenRequest(
            agent_id="agent-xyz",
            destination_url="https://other.example.com/api/data",
            amount_requested=0.001,
            purpose="test",
        )
        token = issue_token(req, private_key).token

        resp = client.get(ENDPOINT, headers=_auth(token))
        assert resp.status_code == 403
        body = resp.json()
        assert body["error_code"] == "DESTINATION_MISMATCH"
        assert body["http_status"] == 403

    def test_tampered_token_returns_400(self, client, valid_token):
        resp = client.get(ENDPOINT, headers=_auth(_tampered_token(valid_token)))
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"

    def test_garbage_token_returns_400(self, client):
        resp = client.get(ENDPOINT, headers=_auth("not.a.jwt"))
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"

    def test_token_signed_with_different_key_returns_400(self, client, keypair):
        """別の鍵ペアで署名されたトークンは検証に失敗する。"""
        other_private, _ = generate_keypair()
        req = TokenRequest(
            agent_id="agent-xyz",
            destination_url=MERCHANT_URL,
            amount_requested=0.001,
            purpose="test",
        )
        token = issue_token(req, other_private).token

        resp = client.get(ENDPOINT, headers=_auth(token))
        assert resp.status_code == 400

    def test_expired_takes_priority_over_wrong_destination(self, client, keypair):
        """期限切れ + 宛先不一致の場合は TOKEN_EXPIRED を優先する。"""
        private_key, _ = keypair
        token = _expired_token(private_key, "https://other.example.com/")

        resp = client.get(ENDPOINT, headers=_auth(token))
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "TOKEN_EXPIRED"


# ---------------------------------------------------------------------------
# 代替コンストラクタ
# ---------------------------------------------------------------------------

class TestAlternativeConstructors:
    def test_from_agentpass_config(self, keypair):
        private_key, public_key = keypair
        config = _make_agentpass_config(public_key)

        inner = Starlette(routes=[Route(ENDPOINT, _ok_handler)])
        app = AgentPassMiddleware.from_agentpass_config(inner, config)
        client = TestClient(app, base_url=BASE_URL)

        req = TokenRequest(
            agent_id="agent-xyz",
            destination_url=MERCHANT_URL,
            amount_requested=0.001,
            purpose="test",
        )
        token = issue_token(req, private_key).token

        resp = client.get(ENDPOINT, headers=_auth(token))
        assert resp.status_code == 200

    def test_from_agentpass_url_with_mock_fetch(self, keypair):
        """_fetch を差し込むことで外部通信なしに自律取得パターンをテストする。"""
        private_key, public_key = keypair
        config = _make_agentpass_config(public_key)

        def _mock_fetch(url: str) -> bytes:
            assert "/.well-known/agentpass.json" in url
            return config.model_dump_json().encode()

        inner = Starlette(routes=[Route(ENDPOINT, _ok_handler)])
        app = AgentPassMiddleware.from_agentpass_url(
            inner, "https://agentpass.example.com", _fetch=_mock_fetch
        )
        client = TestClient(app, base_url=BASE_URL)

        req = TokenRequest(
            agent_id="agent-xyz",
            destination_url=MERCHANT_URL,
            amount_requested=0.001,
            purpose="test",
        )
        token = issue_token(req, private_key).token

        resp = client.get(ENDPOINT, headers=_auth(token))
        assert resp.status_code == 200

    def test_from_agentpass_url_blocks_bad_token(self, keypair):
        """自律取得パターンでも不正トークンは弾かれる。"""
        private_key, public_key = keypair
        config = _make_agentpass_config(public_key)

        def _mock_fetch(url: str) -> bytes:
            return config.model_dump_json().encode()

        inner = Starlette(routes=[Route(ENDPOINT, _ok_handler)])
        app = AgentPassMiddleware.from_agentpass_url(
            inner, "https://agentpass.example.com", _fetch=_mock_fetch
        )
        client = TestClient(app, base_url=BASE_URL)

        resp = client.get(ENDPOINT, headers=_auth("garbage.token.here"))
        assert resp.status_code == 400
