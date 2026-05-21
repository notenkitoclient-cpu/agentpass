# AgentPass

**AgentPass is a neutral trust infrastructure for AI agents.**

Delegated payment authorization · Replayable transaction audit · Sandbox-safe agent commerce · Multi-LLM compatible trust flows

```
Agent  ──[AgentPass JWT]──▶  Merchant API
              ▲ Ed25519 署名 + aud 固定 + jti 使い捨て
```

---

## What AgentPass Solves

| 問題 | AgentPass の対策 |
|------|----------------|
| **リプレイ攻撃** | `jti` クレームで各トークンを使い捨て。傍受されたトークンを再送しても即拒否 |
| **なりすまし** | Ed25519 署名でトークンを発行元エージェントの鍵ペアに紐付け。偽造不可 |
| **APIキー共有** | エージェントごとに独立した鍵ペア。1つの鍵が漏洩しても他に影響なし |

---

## Try AgentPass in 3 Minutes

> **Requires Python 3.13+**

### Step 1 — Install

**Recommended: uv**

```bash
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip install agentpass-ai
```

**Alternative: pip**

```bash
pip install agentpass-ai
```

> Install package: `agentpass-ai` / Import package: `agentpass`  
> `cryptography`, `PyJWT`, `fastapi`, `httpx`, `pydantic` are bundled — no separate install needed.

### Step 2 — Create `quickdemo.py`

```python
from agentpass import issue_token, verify_token, TokenRequest, generate_keypair

ENDPOINT = "https://api.example.com/v1/query"

private_key, public_key = generate_keypair()

token = issue_token(
    TokenRequest(
        agent_id="agent-demo-001",
        destination_url=ENDPOINT,
        amount_requested=0.001,
        purpose="data query",
    ),
    private_key,
).token

claims = verify_token(token, public_key, ENDPOINT)
print(f"✓ Verified  agent={claims.agent_id}  amount={claims.amount} {claims.currency}")
print(f"  token={token[:52]}...")
```

### Step 3 — Run

```bash
python quickdemo.py
```

### Success

If you see this output, AgentPass is working correctly:

```
✓ Verified  agent=agent-demo-001  amount=0.001 JPY
  token=eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZ2V...
```

`✓ Verified` が表示されたら成功です。

### Docker Demo

Optional — not required for the first demo.  
Replay-safe フローを Docker で試すには → [`examples/`](examples/README.md)

---

## ASGI Middleware Setup

FastAPI / Starlette への組み込みは3ファイルで完了します。

### 1. インストール

> **Requires Python 3.13+**

```bash
pip install agentpass-ai uvicorn
```

> **Note:** Install package: `agentpass-ai` / Import package: `agentpass`  
> `fastapi`, `cryptography`, `PyJWT`, `httpx`, `pydantic` are bundled.

### 2. 加盟店サーバー (`merchant.py`)

```python
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

### 3. `agentpass.json` を公開する

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

`https://api.merchant.com/.well-known/agentpass.json` で配信します。`public_key` はエージェントが事前登録した Ed25519 公開鍵（hex）を設定してください。

### 4. エージェント (`agent.py`)

```python
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

### 5. 起動

```bash
# Terminal 1
uvicorn merchant:app

# Terminal 2
python agent.py
```

> **Note:** 上記は構成例です。ローカルで動かせる完全なデモは [`examples/`](examples/README.md) を参照してください。

---

## Security Model

| 防衛壁 | 仕組み | 防御する攻撃 |
|--------|--------|-------------|
| **Ed25519 署名** | トークンをエージェントの秘密鍵で署名。公開鍵は `agentpass.json` から自律取得 | 偽造・なりすまし |
| **改ざん検知** | JWT 三部構造。1バイトでも変更すれば検証失敗 | 中間者改ざん |
| **`aud` 宛先固定** | 完全URLを埋め込み、受信URLと完全一致チェック | トークン横流し |
| **`jti` 使い捨て** | `AnomalyDetector` が JTI を TTL 付きで記録し、再送を即拒否 | リプレイ攻撃 |

クローラーは **SSRF防御**（プライベートIPへの解決を即拒否）と **1MBストリーム制限**（巨大レスポンスで即切断）を内蔵しています。

---

## Architecture

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

## Error Reference

| HTTP | `error_code` | 原因 |
|------|-------------|------|
| 400 | `INVALID_PAYLOAD` | 署名不一致 / 必須クレーム欠如 |
| 401 | `INVALID_PAYLOAD` | Authorizationヘッダー欠如 / スキーム誤り / JWT不正 |
| 401 | `TOKEN_EXPIRED` | JWTの `exp` 超過 |
| 403 | `DESTINATION_MISMATCH` | `aud` が要求URLと不一致 |
| 403 | `REPLAY_ATTACK` | 同一JTIのトークンを再送信 |
| 503 | `MERCHANT_UNVERIFIED` | `agentpass.json` の取得失敗 |

---

## Tests

```bash
pytest
pytest --cov=src --cov-report=term-missing  # カバレッジ付き
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

### Sandbox（110件）— プロトコル境界検証

| ファイル | カバー範囲 | 件数 |
|---------|-----------|-----:|
| `tests/sandbox/test_budget_exceeded_returns_402.py` | Budget Control・HTTP 402拒否 | 20 |
| `tests/sandbox/test_budget_rejection_audit_log.py` | append-only JSONL監査ログ | 16 |
| `tests/sandbox/test_budget_replay.py` | 拒否イベントのreplay検証 | 8 |
| `tests/sandbox/test_exp005b_jti_collision.py` | JTI衝突・スレッド安全性（N並列→承認1件） | 16 |
| `tests/sandbox/test_exp006_burst_freeze.py` | バースト検知・一時freeze（HTTP 503） | 22 |
| `tests/sandbox/test_exp005c_agent_keypair_isolation.py` | エージェント別鍵隔離・signer mismatch拒否 | 28 |

---

## License

MIT License — 商用利用・改変・再配布自由。

---

## Feedback

Found onboarding friction or integration issues?

Please open a GitHub issue:
https://github.com/notenkitoclient-cpu/agentpass/issues
