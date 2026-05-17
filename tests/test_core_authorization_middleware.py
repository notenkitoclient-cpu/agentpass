"""
src/core/authorization_middleware.py のテスト

モック AgentPassCrawler を注入して外部通信ゼロ・決定論的に動作する。
asyncio_mode = "auto" を pyproject.toml に設定済みのため @pytest.mark.asyncio は省略。
"""

from __future__ import annotations

import time
import uuid

import jwt as _jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from core.agentpass_crawler import MerchantMetadata, PricingSchema
from core.authorization_middleware import AuthorizationMiddleware

# ---------------------------------------------------------------------------
# テスト定数
# ---------------------------------------------------------------------------

ISS_DOMAIN = "agent.example.com"
MERCHANT_BASE = "https://merchant.example.com"
ENDPOINT_PATH = "/api/data"
MERCHANT_URL = f"{MERCHANT_BASE}{ENDPOINT_PATH}"


# ---------------------------------------------------------------------------
# テスト用ユーティリティ
# ---------------------------------------------------------------------------

class _MockCrawler:
    """fetch_merchant_metadata を制御できるモッククローラー。"""

    def __init__(self, metadata: MerchantMetadata | None = None, raises: Exception | None = None):
        self._metadata = metadata
        self._raises = raises

    async def fetch_merchant_metadata(self, domain: str) -> MerchantMetadata:
        if self._raises is not None:
            raise self._raises
        return self._metadata


def _make_key_pair():
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def _make_metadata(public_key) -> MerchantMetadata:
    pub_hex = public_key.public_bytes_raw().hex()
    return MerchantMetadata(
        agentpass_version="1.0.0",
        merchant_id=str(uuid.uuid4()),
        public_key=pub_hex,
        pricing=[PricingSchema(endpoint="/api/data", price_per_token=0.001)],
    )


def _make_token(
    private_key,
    *,
    iss: str = ISS_DOMAIN,
    aud: str = MERCHANT_URL,
    exp_delta: int = 60,
    extra: dict | None = None,
) -> str:
    now = int(time.time())
    payload: dict = {
        "sub": str(uuid.uuid4()),
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + exp_delta,
        "jti": str(uuid.uuid4()),
        "amt": 0.001,
        "cur": "JPY",
        "agp": "1",
    }
    if extra:
        payload.update(extra)
    return _jwt.encode(payload, private_key, algorithm="EdDSA")


def _make_app(crawler=None) -> Starlette:
    async def endpoint(request: Request) -> JSONResponse:
        claims = request.state.agent_claims
        return JSONResponse({"agent_id": claims.agent_id})

    app = Starlette(routes=[Route(ENDPOINT_PATH, endpoint)])
    app.add_middleware(AuthorizationMiddleware, crawler=crawler)
    return app


# ---------------------------------------------------------------------------
# 正常系
# ---------------------------------------------------------------------------

class TestNormalCase:
    def setup_method(self):
        self.private_key, self.public_key = _make_key_pair()
        self.metadata = _make_metadata(self.public_key)
        self.crawler = _MockCrawler(metadata=self.metadata)
        self.client = TestClient(_make_app(self.crawler), base_url=MERCHANT_BASE)

    def test_valid_token_returns_200(self):
        token = _make_token(self.private_key)
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert resp.status_code == 200

    def test_agent_claims_bound_to_request_state(self):
        token = _make_token(self.private_key)
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert "agent_id" in resp.json()

    def test_agent_id_matches_token_sub(self):
        agent_id = str(uuid.uuid4())
        token = _make_token(self.private_key, extra={"sub": agent_id})
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert resp.json()["agent_id"] == agent_id


# ---------------------------------------------------------------------------
# Authorization ヘッダー検証
# ---------------------------------------------------------------------------

class TestHeaderValidation:
    def setup_method(self):
        private_key, public_key = _make_key_pair()
        metadata = _make_metadata(public_key)
        self.crawler = _MockCrawler(metadata=metadata)
        self.client = TestClient(_make_app(self.crawler), base_url=MERCHANT_BASE)

    def test_missing_header_returns_401(self):
        resp = self.client.get(ENDPOINT_PATH)
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"

    def test_bearer_scheme_returns_401(self):
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": "Bearer sometoken"})
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"

    def test_basic_scheme_returns_401(self):
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"

    def test_lowercase_agentpass_scheme_returns_401(self):
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": "agentpass sometoken"})
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"

    def test_empty_token_after_scheme_returns_401(self):
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": "AgentPass "})
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"


# ---------------------------------------------------------------------------
# JWT パース段階の失敗
# ---------------------------------------------------------------------------

class TestJwtParsing:
    def setup_method(self):
        private_key, public_key = _make_key_pair()
        metadata = _make_metadata(public_key)
        self.crawler = _MockCrawler(metadata=metadata)
        self.client = TestClient(_make_app(self.crawler), base_url=MERCHANT_BASE)

    def test_malformed_jwt_returns_400(self):
        resp = self.client.get(
            ENDPOINT_PATH,
            headers={"Authorization": "AgentPass not.a.validjwt!!!"},
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"

    def test_missing_iss_claim_returns_400(self):
        private_key, _ = _make_key_pair()
        now = int(time.time())
        token = _jwt.encode(
            {"sub": "agent", "aud": MERCHANT_URL, "iat": now, "exp": now + 60},
            private_key,
            algorithm="EdDSA",
        )
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"

    def test_plain_string_not_jwt_returns_400(self):
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": "AgentPass plaintext"})
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"


# ---------------------------------------------------------------------------
# クローラー失敗 → 503
# ---------------------------------------------------------------------------

class TestCrawlerFailure:
    def test_crawler_raises_exception_returns_503(self):
        crawler = _MockCrawler(raises=ConnectionError("Network unreachable"))
        client = TestClient(_make_app(crawler), base_url=MERCHANT_BASE)

        private_key, _ = _make_key_pair()
        token = _make_token(private_key)
        resp = client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert resp.status_code == 503
        assert resp.json()["error_code"] == "MERCHANT_UNVERIFIED"

    def test_crawler_raises_value_error_returns_503(self):
        crawler = _MockCrawler(raises=ValueError("Schema validation failed"))
        client = TestClient(_make_app(crawler), base_url=MERCHANT_BASE)

        private_key, _ = _make_key_pair()
        token = _make_token(private_key)
        resp = client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert resp.status_code == 503
        assert resp.json()["error_code"] == "MERCHANT_UNVERIFIED"

    def test_crawler_error_message_contains_iss_domain(self):
        crawler = _MockCrawler(raises=ConnectionError("timeout"))
        client = TestClient(_make_app(crawler), base_url=MERCHANT_BASE)

        private_key, _ = _make_key_pair()
        token = _make_token(private_key)
        resp = client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert ISS_DOMAIN in resp.json()["message"]


# ---------------------------------------------------------------------------
# TokenVerifier 検証失敗
# ---------------------------------------------------------------------------

class TestTokenVerifierFailure:
    def setup_method(self):
        self.private_key, self.public_key = _make_key_pair()
        self.metadata = _make_metadata(self.public_key)
        self.crawler = _MockCrawler(metadata=self.metadata)
        self.client = TestClient(_make_app(self.crawler), base_url=MERCHANT_BASE)

    def test_expired_token_returns_401(self):
        # exp を過去に設定
        token = _make_token(self.private_key, exp_delta=-10)
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert resp.status_code == 401
        assert resp.json()["error_code"] == "TOKEN_EXPIRED"

    def test_wrong_audience_returns_403(self):
        token = _make_token(self.private_key, aud="https://other-merchant.example.com/api/data")
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "DESTINATION_MISMATCH"

    def test_wrong_key_signature_returns_400(self):
        # 別の秘密鍵で署名したトークンを、正しい公開鍵で検証しようとする
        other_private_key, _ = _make_key_pair()
        token = _make_token(other_private_key)
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"

    def test_missing_agentpass_claims_returns_400(self):
        now = int(time.time())
        # amt/cur/agp/jti を含まない普通の JWT
        token = _jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "iss": ISS_DOMAIN,
                "aud": MERCHANT_URL,
                "iat": now,
                "exp": now + 60,
            },
            self.private_key,
            algorithm="EdDSA",
        )
        resp = self.client.get(ENDPOINT_PATH, headers={"Authorization": f"AgentPass {token}"})
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_PAYLOAD"
