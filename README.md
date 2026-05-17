# AgentPass

**AIエージェントのための財布とパスポート。**

AgentPassは、AIエージェント間（M2M）の決済と認証を5分で導入できるオープンソースミドルウェアです。エージェントは署名済みJWTを「パスポート」として提示し、加盟店はその場で自律検証します。中央集権的なAPIキー管理も、サードパーティ認証サーバーも不要です。

```
Agent  ──[AgentPass JWT]──▶  Merchant API
         "I am agent-7f3a, paying 0.001 JPY/token"
              ▲ Ed25519 署名 + aud 固定 + jti 使い捨て
```

---

## 5分クイックスタート

### 1. インストール

```bash
pip install agentpass fastapi uvicorn cryptography PyJWT httpx
```

### 2. 加盟店サーバーにミドルウェアを追加

```python
# merchant_api.py
from fastapi import FastAPI
from starlette.requests import Request

from agentpass import AuthorizationMiddleware, AnomalyDetector

app = FastAPI()
app.add_middleware(
    AuthorizationMiddleware,
    anomaly_detector=AnomalyDetector(),  # リプレイ攻撃検知
)

@app.get("/v1/pay")
async def pay(request: Request):
    claims = request.state.agent_claims   # 検証済みクレームが自動バインド
    return {
        "agent_id": claims.agent_id,
        "amount": claims.amount,
        "currency": claims.currency,
    }
```

### 3. `agentpass.json` を公開する（加盟店側）

```json
{
  "agentpass_version": "1.0.0",
  "merchant_id": "550e8400-e29b-41d4-a716-446655440000",
  "public_key": "a1b2c3d4...",
  "pricing": [
    { "endpoint": "/v1/pay", "price_per_token": 0.001 }
  ]
}
```

加盟店の Ed25519 公開鍵を `https://api.merchant.com/.well-known/agentpass.json` で配信します。

### 4. エージェント側でトークンを発行して送信

```python
# agent_client.py
from agentpass import issue_token, TokenRequest, generate_keypair
import httpx

# 実際はセキュアストレージから秘密鍵を読み込む
private_key, _ = generate_keypair()

req = TokenRequest(
    agent_id="agent-7f3a...",
    destination_url="https://api.merchant.com/v1/pay",
    amount_requested=0.001,
    purpose="data access",
)
issued = issue_token(req, private_key)

resp = httpx.get(
    "https://api.merchant.com/v1/pay",
    headers={"Authorization": f"AgentPass {issued.token}"},
)
print(resp.json())  # {"agent_id": "agent-7f3a...", "amount": 0.001, "currency": "JPY"}
```

これだけです。

---

## 4つの防衛壁

| 防衛壁 | 仕組み | 防御する攻撃 |
|--------|--------|-------------|
| **Ed25519 署名** | トークンをエージェントの秘密鍵で署名。公開鍵は `agentpass.json` から自律取得 | 偽造・なりすまし |
| **改ざん検知** | JWT ヘッダー・ペイロード・署名の三部構造。1バイトでも変更すれば検証失敗 | 中間者改ざん |
| **`aud` 宛先固定** | `aud` クレームに完全URLを埋め込み、受信URLと完全一致チェック | トークン横流し |
| **`jti` 使い捨て** | `AnomalyDetector` が JTI を TTL 付きで記録し、再送を即拒否 | リプレイ攻撃 |

さらに、クローラーは **SSRF防御**（プライベートIPへの解決を即拒否）と **1MBストリーム制限**（巨大レスポンスで即切断）を内蔵しています。

---

## アーキテクチャ

```
┌─────────────────────────────────────────────────────┐
│                  AgentPass Core                      │
│                                                      │
│  AuthorizationMiddleware (ASGI)                      │
│    │                                                 │
│    ├─▶ AgentPassCrawler          ├─▶ TTL Cache       │
│    │     └─▶ SSRF Protection     └─▶ 1MB Limit       │
│    │                                                  │
│    ├─▶ TokenVerifier (Ed25519 + aud + exp)           │
│    │                                                  │
│    └─▶ AnomalyDetector (jti replay defense)          │
│                                                      │
└─────────────────────────────────────────────────────┘
```

| モジュール | 役割 |
|-----------|------|
| `AgentPassCrawler` | `agentpass.json` の非同期取得・SSRF防御・TTLキャッシュ |
| `TokenVerifier` | Ed25519署名検証・`aud`/`exp`チェック・必須クレーム検証 |
| `AnomalyDetector` | JTIベースのリプレイ攻撃検知・期限切れエントリのGC |
| `AuthorizationMiddleware` | 上記3つを統合するASGIミドルウェア |

---

## エラーレスポンス一覧

| HTTP | `error_code` | 原因 |
|------|-------------|------|
| 400 | `INVALID_PAYLOAD` | 署名不一致 / 必須クレーム欠如 |
| 401 | `INVALID_PAYLOAD` | Authorizationヘッダー欠如 / スキーム誤り / JWT不正 |
| 401 | `TOKEN_EXPIRED` | JWTの `exp` 超過 |
| 403 | `DESTINATION_MISMATCH` | `aud` が要求URLと不一致 |
| 403 | `REPLAY_ATTACK` | 同一JTIのトークンを再送信 |
| 503 | `MERCHANT_UNVERIFIED` | `agentpass.json` の取得失敗 |

---

## 3ホライゾン戦略

| ホライゾン | フェーズ | 内容 |
|-----------|---------|------|
| **波1** | OSS配布（現在） | `pip install agentpass` で5分導入。ゴールドラッシュのスコップ屋として、AIエージェント爆増の波に乗るインフラを先占する |
| **波2** | 双方向マーケット | 検証済みエージェントの `AgentID` 信用スコアを公開APIで提供。加盟店はスコアで与信枠を動的制御。エージェントはスコアを資産として蓄積 |
| **波3** | M2M中央銀行 | エージェント間決済の清算・為替・流動性プールを提供。AI経済圏のレールになる |

---

## テスト

```bash
# 全テスト実行
pytest

# カバレッジ付き
pytest --cov=src --cov-report=term-missing
```

**263 tests, 0 failed**（Python 3.14）

### Core（153件）

| ファイル | カバー範囲 | 件数 |
|---------|-----------|-----:|
| `tests/test_agentpass_crawler.py` | SSRF防御・1MB制限・TTLキャッシュ・HTTP異常系 | 20 |
| `tests/test_authorization_middleware.py` | ミドルウェア全経路（正常・異常・JWT検証） | 20 |
| `tests/test_core_authorization_middleware.py` | Pydanticスキーマ統合・エラーコード体系 | 18 |
| `tests/test_circuit_breaker.py` | 予算・レート制限・スライディングウィンドウ | 22 |
| `tests/test_token_verifier.py` | Ed25519署名・aud・exp・クレーム検証 | 15 |
| `tests/test_token_issuer.py` | トークン発行・JTI一意性 | 9 |
| `tests/test_anomaly_detector.py` | リプレイ検知・GC・時刻制御 | 11 |
| `tests/test_credit_scorer.py` | 信用スコア計算・ペナルティ・境界値 | 22 |
| `tests/test_agent_signer.py` | AgentID導出・決定論性 | 9 |
| `tests/e2e/test_agentpass_ecosystem.py` | フルスタック統合（正常系・リプレイ攻撃） | 7 |

### Sandbox（110件）— 経済動作検証実験

| ファイル | カバー範囲 | 件数 |
|---------|-----------|-----:|
| `tests/sandbox/test_budget_exceeded_returns_402.py` | Budget Control・HTTP 402拒否 | 20 |
| `tests/sandbox/test_budget_rejection_audit_log.py` | append-only JSONL監査ログ | 16 |
| `tests/sandbox/test_budget_replay.py` | 拒否イベントのreplay検証 | 8 |
| `tests/sandbox/test_exp005b_jti_collision.py` | JTI衝突・スレッド安全性（N並列→承認1件） | 16 |
| `tests/sandbox/test_exp006_burst_freeze.py` | バースト検知・一時freeze（HTTP 503） | 22 |
| `tests/sandbox/test_exp005c_agent_keypair_isolation.py` | エージェント別鍵隔離・signer mismatch拒否 | 28 |

---

## ライセンス

MIT License — 商用利用・改変・再配布自由。

---

> *"AIエージェントが人間と同じように経済活動する時代に、AgentPassはその入国審査官になる。"*
