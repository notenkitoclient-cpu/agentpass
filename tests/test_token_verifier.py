"""token_verifier の動作確認テスト — 正常系・異常系を網羅"""

import time
import uuid

import jwt
import pytest

from src.core.token_issuer import TokenRequest, generate_keypair, issue_token
from src.core.token_verifier import (
    DestinationMismatchError,
    InvalidPayloadError,
    TokenExpiredError,
    VerifiedClaims,
    verify_token,
)

MERCHANT_URL = "https://merchant.example.com/api/data"


@pytest.fixture(scope="module")
def keypair():
    return generate_keypair()


@pytest.fixture
def valid_issued_token(keypair):
    private_key, _ = keypair
    req = TokenRequest(
        agent_id="agent-xyz",
        destination_url=MERCHANT_URL,
        amount_requested=0.005,
        purpose="fetch market data",
    )
    return issue_token(req, private_key)


def _make_raw_token(private_key, payload: dict) -> str:
    """テスト用：任意のペイロードでJWTを直接生成する。"""
    return jwt.encode(payload, private_key, algorithm="EdDSA")


def _base_payload() -> dict:
    now = int(time.time())
    return {
        "sub": "agent-xyz",
        "aud": MERCHANT_URL,
        "iat": now,
        "exp": now + 60,
        "jti": str(uuid.uuid4()),
        "amt": 0.005,
        "cur": "JPY",
        "agp": "1",
    }


# ---------------------------------------------------------------------------
# 正常系
# ---------------------------------------------------------------------------

class TestVerifyTokenNormalCase:
    def test_returns_verified_claims(self, keypair, valid_issued_token):
        _, public_key = keypair
        result = verify_token(valid_issued_token.token, public_key, MERCHANT_URL)
        assert isinstance(result, VerifiedClaims)

    def test_claims_match_issued_token(self, keypair, valid_issued_token):
        _, public_key = keypair
        result = verify_token(valid_issued_token.token, public_key, MERCHANT_URL)

        assert result.agent_id == "agent-xyz"
        assert result.destination_url == MERCHANT_URL
        assert result.amount == 0.005
        assert result.currency == "JPY"
        assert result.token_id == valid_issued_token.token_id

    def test_timestamps_are_integers(self, keypair, valid_issued_token):
        _, public_key = keypair
        result = verify_token(valid_issued_token.token, public_key, MERCHANT_URL)

        assert isinstance(result.issued_at, int)
        assert isinstance(result.expires_at, int)
        assert result.expires_at > result.issued_at


# ---------------------------------------------------------------------------
# 異常系 — 400 INVALID_PAYLOAD
# ---------------------------------------------------------------------------

class TestInvalidPayload:
    def test_tampered_signature_raises(self, keypair, valid_issued_token):
        _, public_key = keypair
        parts = valid_issued_token.token.split(".")
        tampered = parts[0] + "." + parts[1] + ".AAAA_invalidsig_ZZZZ"

        with pytest.raises(InvalidPayloadError) as exc_info:
            verify_token(tampered, public_key, MERCHANT_URL)

        assert exc_info.value.http_status == 400
        assert exc_info.value.error_code == "INVALID_PAYLOAD"

    def test_garbage_string_raises(self, keypair):
        _, public_key = keypair

        with pytest.raises(InvalidPayloadError):
            verify_token("not.a.jwt", public_key, MERCHANT_URL)

    def test_empty_string_raises(self, keypair):
        _, public_key = keypair

        with pytest.raises(InvalidPayloadError):
            verify_token("", public_key, MERCHANT_URL)

    def test_missing_amt_claim_raises(self, keypair):
        private_key, public_key = keypair
        payload = _base_payload()
        del payload["amt"]
        token = _make_raw_token(private_key, payload)

        with pytest.raises(InvalidPayloadError) as exc_info:
            verify_token(token, public_key, MERCHANT_URL)

        assert "amt" in str(exc_info.value)

    def test_missing_agentpass_version_raises(self, keypair):
        private_key, public_key = keypair
        payload = _base_payload()
        del payload["agp"]
        token = _make_raw_token(private_key, payload)

        with pytest.raises(InvalidPayloadError) as exc_info:
            verify_token(token, public_key, MERCHANT_URL)

        assert "agp" in str(exc_info.value)

    def test_missing_jti_raises(self, keypair):
        """jtiがないとリプレイ攻撃防止ができないため弾く。"""
        private_key, public_key = keypair
        payload = _base_payload()
        del payload["jti"]
        token = _make_raw_token(private_key, payload)

        with pytest.raises(InvalidPayloadError) as exc_info:
            verify_token(token, public_key, MERCHANT_URL)

        assert "jti" in str(exc_info.value)

    def test_wrong_public_key_raises(self, keypair, valid_issued_token):
        """発行に使っていない別の公開鍵では検証できない。"""
        _, different_public_key = generate_keypair()

        with pytest.raises(InvalidPayloadError):
            verify_token(valid_issued_token.token, different_public_key, MERCHANT_URL)


# ---------------------------------------------------------------------------
# 異常系 — 401 TOKEN_EXPIRED
# ---------------------------------------------------------------------------

class TestTokenExpired:
    def test_expired_token_raises(self, keypair):
        private_key, public_key = keypair
        now = int(time.time())
        payload = _base_payload()
        payload["iat"] = now - 120
        payload["exp"] = now - 60   # 60秒前に失効済み
        token = _make_raw_token(private_key, payload)

        with pytest.raises(TokenExpiredError) as exc_info:
            verify_token(token, public_key, MERCHANT_URL)

        assert exc_info.value.http_status == 401
        assert exc_info.value.error_code == "TOKEN_EXPIRED"

    def test_expired_takes_priority_over_wrong_destination(self, keypair):
        """期限切れ + 宛先不一致の場合は TOKEN_EXPIRED を優先する。"""
        private_key, public_key = keypair
        now = int(time.time())
        payload = _base_payload()
        payload["iat"] = now - 120
        payload["exp"] = now - 60
        payload["aud"] = "https://wrong.example.com/api"
        token = _make_raw_token(private_key, payload)

        # PyJWT は exp → aud の順に検証するため TOKEN_EXPIRED が先に来る
        with pytest.raises(TokenExpiredError):
            verify_token(token, public_key, MERCHANT_URL)


# ---------------------------------------------------------------------------
# 異常系 — 403 DESTINATION_MISMATCH
# ---------------------------------------------------------------------------

class TestDestinationMismatch:
    def test_wrong_merchant_url_raises(self, keypair, valid_issued_token):
        _, public_key = keypair

        with pytest.raises(DestinationMismatchError) as exc_info:
            verify_token(
                valid_issued_token.token,
                public_key,
                "https://attacker.example.com/steal",
            )

        assert exc_info.value.http_status == 403
        assert exc_info.value.error_code == "DESTINATION_MISMATCH"

    def test_subdomain_does_not_match(self, keypair, valid_issued_token):
        """サブドメインが違えば別URLとして弾く（前方一致は許さない）。"""
        _, public_key = keypair

        with pytest.raises(DestinationMismatchError):
            verify_token(
                valid_issued_token.token,
                public_key,
                "https://sub.merchant.example.com/api/data",
            )

    def test_extra_path_does_not_match(self, keypair, valid_issued_token):
        """パスが1文字でも違えば弾く。"""
        _, public_key = keypair

        with pytest.raises(DestinationMismatchError):
            verify_token(
                valid_issued_token.token,
                public_key,
                MERCHANT_URL + "/extra",
            )
