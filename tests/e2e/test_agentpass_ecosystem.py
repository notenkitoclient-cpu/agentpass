"""
Week 4 E2E — AgentPass フルスタック統合テスト

実在する全コアコンポーネント（AuthorizationMiddleware / AgentPassCrawler /
TokenVerifier / AnomalyDetector）を FastAPI アプリ上で完全結合させる。
respx で agentpass.json の HTTP 取得をモックし、外部通信ゼロで動作する。

正常系: 有効トークン → 200 OK・agent_claims バインド確認
異常系: 同一トークンの再送 → AnomalyDetector がリプレイを捕捉 → 403 REPLAY_ATTACK
"""

from __future__ import annotations

import time
import uuid

import httpx
import jwt as _jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from core.anomaly_detector import AnomalyDetector
from core.authorization_middleware import AuthorizationMiddleware

# ---------------------------------------------------------------------------
# テスト定数
# ---------------------------------------------------------------------------

ISS = "example.com"
AGENTPASS_URL = f"https://{ISS}/.well-known/agentpass.json"
MERCHANT_BASE = "https://api.merchant.com"
ENDPOINT = "/v1/pay"
MERCHANT_URL = f"{MERCHANT_BASE}{ENDPOINT}"


# ---------------------------------------------------------------------------
# ファクトリ
# ---------------------------------------------------------------------------

def _build_ecosystem() -> tuple:
    """
    テスト用エコシステム（キーペア・agentpass_json・FastAPI app）を構築して返す。
    呼び出し毎に独立したキーペアと AnomalyDetector を生成する。
    """
    private_key = Ed25519PrivateKey.generate()
    pub_hex = private_key.public_key().public_bytes_raw().hex()

    agentpass_json = {
        "agentpass_version": "1.0.0",
        "merchant_id": str(uuid.uuid4()),
        "public_key": pub_hex,
        "pricing": [{"endpoint": ENDPOINT, "price_per_token": 0.001}],
    }

    anomaly_detector = AnomalyDetector()

    app = FastAPI()
    # crawler=None → 実際の AgentPassCrawler（httpx）を使用 → respx でモック
    app.add_middleware(AuthorizationMiddleware, anomaly_detector=anomaly_detector)

    @app.get(ENDPOINT)
    async def pay(request: Request):
        claims = request.state.agent_claims
        return {
            "status": "ok",
            "agent_id": claims.agent_id,
            "amount": claims.amount,
        }

    return private_key, agentpass_json, app


def _issue_token(
    private_key: Ed25519PrivateKey,
    *,
    jti: str | None = None,
    exp_delta: int = 60,
) -> str:
    """iss・AgentPass 必須クレームを含む EdDSA JWT を発行する。"""
    now = int(time.time())
    return _jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iss": ISS,
            "aud": MERCHANT_URL,
            "iat": now,
            "exp": now + exp_delta,
            "jti": jti or str(uuid.uuid4()),
            "amt": 0.001,
            "cur": "JPY",
            "agp": "1",
        },
        private_key,
        algorithm="EdDSA",
    )


# ---------------------------------------------------------------------------
# 正常系シナリオ
# ---------------------------------------------------------------------------

class TestNormalScenario:
    def test_valid_token_returns_200(self):
        """有効なトークン → HTTP 200 が返ること。"""
        private_key, agentpass_json, app = _build_ecosystem()
        token = _issue_token(private_key)

        with respx.mock:
            respx.get(AGENTPASS_URL).mock(
                return_value=httpx.Response(200, json=agentpass_json)
            )
            client = TestClient(app, base_url=MERCHANT_BASE)
            resp = client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token}"})

        assert resp.status_code == 200

    def test_valid_token_binds_agent_id(self):
        """agent_claims が下流エンドポイントへ正しくバインドされること。"""
        private_key, agentpass_json, app = _build_ecosystem()
        token = _issue_token(private_key)

        with respx.mock:
            respx.get(AGENTPASS_URL).mock(
                return_value=httpx.Response(200, json=agentpass_json)
            )
            client = TestClient(app, base_url=MERCHANT_BASE)
            resp = client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token}"})

        body = resp.json()
        assert "agent_id" in body
        assert body["amount"] == pytest.approx(0.001)

    def test_two_different_tokens_both_pass(self):
        """JTI が異なるトークンは連続して送信しても両方 200 であること。"""
        private_key, agentpass_json, app = _build_ecosystem()
        token1 = _issue_token(private_key)
        token2 = _issue_token(private_key)

        with respx.mock:
            respx.get(AGENTPASS_URL).mock(
                return_value=httpx.Response(200, json=agentpass_json)
            )
            client = TestClient(app, base_url=MERCHANT_BASE)
            resp1 = client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token1}"})
            resp2 = client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token2}"})

        assert resp1.status_code == 200
        assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# 異常系シナリオ — リプレイ攻撃
# ---------------------------------------------------------------------------

class TestReplayAttackScenario:
    def test_replay_returns_403(self):
        """同一トークンの 2 回目送信は 403 Forbidden であること。"""
        private_key, agentpass_json, app = _build_ecosystem()
        jti = str(uuid.uuid4())
        token = _issue_token(private_key, jti=jti)

        with respx.mock:
            respx.get(AGENTPASS_URL).mock(
                return_value=httpx.Response(200, json=agentpass_json)
            )
            client = TestClient(app, base_url=MERCHANT_BASE)
            resp1 = client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token}"})
            resp2 = client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token}"})

        assert resp1.status_code == 200
        assert resp2.status_code == 403

    def test_replay_error_code_is_replay_attack(self):
        """リプレイ攻撃のエラーコードが REPLAY_ATTACK であること。"""
        private_key, agentpass_json, app = _build_ecosystem()
        token = _issue_token(private_key)

        with respx.mock:
            respx.get(AGENTPASS_URL).mock(
                return_value=httpx.Response(200, json=agentpass_json)
            )
            client = TestClient(app, base_url=MERCHANT_BASE)
            client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token}"})
            resp = client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token}"})

        assert resp.json()["error_code"] == "REPLAY_ATTACK"

    def test_third_replay_also_blocked(self):
        """3 回目以降の同一トークン送信も 403 であること。"""
        private_key, agentpass_json, app = _build_ecosystem()
        token = _issue_token(private_key)

        with respx.mock:
            respx.get(AGENTPASS_URL).mock(
                return_value=httpx.Response(200, json=agentpass_json)
            )
            client = TestClient(app, base_url=MERCHANT_BASE)
            client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token}"})
            resp2 = client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token}"})
            resp3 = client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token}"})

        assert resp2.status_code == 403
        assert resp3.status_code == 403

    def test_replay_does_not_block_other_tokens(self):
        """リプレイ検知が他の有効なトークンに影響しないこと。"""
        private_key, agentpass_json, app = _build_ecosystem()
        token_a = _issue_token(private_key)
        token_b = _issue_token(private_key)

        with respx.mock:
            respx.get(AGENTPASS_URL).mock(
                return_value=httpx.Response(200, json=agentpass_json)
            )
            client = TestClient(app, base_url=MERCHANT_BASE)
            # token_a を 2 回送信してリプレイを発生させる
            client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token_a}"})
            client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token_a}"})
            # token_b（別の JTI）は正常通過すること
            resp_b = client.get(ENDPOINT, headers={"Authorization": f"AgentPass {token_b}"})

        assert resp_b.status_code == 200
