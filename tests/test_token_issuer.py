"""token_issuer の動作確認テスト"""

from datetime import timezone

import jwt
import pytest

from core.token_issuer import (
    IssuedToken,
    TokenRequest,
    generate_keypair,
    issue_token,
)


@pytest.fixture
def keypair():
    return generate_keypair()


class TestTokenRequest:
    def test_rejects_http_url(self):
        with pytest.raises(ValueError, match="HTTPS"):
            TokenRequest(
                agent_id="agent-1",
                destination_url="http://example.com/api",
                amount_requested=0.001,
                purpose="test",
            )

    def test_rejects_zero_amount(self):
        with pytest.raises(ValueError, match="positive"):
            TokenRequest(
                agent_id="agent-1",
                destination_url="https://example.com/api",
                amount_requested=0,
                purpose="test",
            )

    def test_rejects_expires_over_300(self):
        with pytest.raises(ValueError, match="300"):
            TokenRequest(
                agent_id="agent-1",
                destination_url="https://example.com/api",
                amount_requested=0.001,
                purpose="test",
                expires_in_seconds=301,
            )

    def test_rejects_long_purpose(self):
        with pytest.raises(ValueError, match="128"):
            TokenRequest(
                agent_id="agent-1",
                destination_url="https://example.com/api",
                amount_requested=0.001,
                purpose="x" * 129,
            )


class TestIssueToken:
    def test_returns_issued_token(self, keypair):
        private_key, _ = keypair
        req = TokenRequest(
            agent_id="agent-abc",
            destination_url="https://api.example.com/data",
            amount_requested=0.001,
            purpose="fetch search results",
        )

        result = issue_token(req, private_key)

        assert isinstance(result, IssuedToken)
        assert result.agent_id == "agent-abc"
        assert result.destination_url == "https://api.example.com/data"
        assert result.max_amount == 0.001

    def test_token_is_verifiable_with_public_key(self, keypair):
        private_key, public_key = keypair
        req = TokenRequest(
            agent_id="agent-abc",
            destination_url="https://api.example.com/data",
            amount_requested=0.001,
            purpose="test",
        )

        result = issue_token(req, private_key)

        # 公開鍵で署名を検証し、クレームを確認
        claims = jwt.decode(
            result.token,
            public_key,
            algorithms=["EdDSA"],
            audience="https://api.example.com/data",
        )

        assert claims["sub"] == "agent-abc"
        assert claims["aud"] == "https://api.example.com/data"
        assert claims["amt"] == 0.001
        assert claims["cur"] == "JPY"
        assert claims["agp"] == "1"
        assert "jti" in claims  # リプレイ防止ID

    def test_each_token_has_unique_jti(self, keypair):
        private_key, public_key = keypair
        req = TokenRequest(
            agent_id="agent-abc",
            destination_url="https://api.example.com/data",
            amount_requested=0.001,
            purpose="test",
        )

        token_a = issue_token(req, private_key)
        token_b = issue_token(req, private_key)

        assert token_a.token_id != token_b.token_id

    def test_token_expiry_is_respected(self, keypair):
        private_key, public_key = keypair
        req = TokenRequest(
            agent_id="agent-abc",
            destination_url="https://api.example.com/data",
            amount_requested=0.001,
            purpose="test",
            expires_in_seconds=60,
        )

        result = issue_token(req, private_key)

        assert result.valid_until.tzinfo == timezone.utc
        claims = jwt.decode(
            result.token,
            public_key,
            algorithms=["EdDSA"],
            audience="https://api.example.com/data",
        )
        exp_delta = claims["exp"] - claims["iat"]
        assert exp_delta == 60

    def test_tampered_token_fails_verification(self, keypair):
        private_key, public_key = keypair
        req = TokenRequest(
            agent_id="agent-abc",
            destination_url="https://api.example.com/data",
            amount_requested=0.001,
            purpose="test",
        )

        result = issue_token(req, private_key)

        # 署名部分を書き換えて改ざんを試みる
        parts = result.token.split(".")
        tampered = parts[0] + "." + parts[1] + ".invalidsignature"

        with pytest.raises(Exception):
            jwt.decode(
                tampered,
                public_key,
                algorithms=["EdDSA"],
                audience="https://api.example.com/data",
            )
