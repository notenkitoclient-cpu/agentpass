# AgentPass — 5-Minute Demo

このデモでは **replay-safe** な M2M 認証フローを実際に動かして確認できます。

```
Agent  ──[AgentPass JWT]──▶  Merchant API
              ↑ Ed25519 署名 + aud 宛先固定 + jti 使い捨て
```

---

## Quick Start (Docker)

```bash
# このディレクトリから実行
cd examples
docker compose up
```

これだけです。以下の順で自動実行されます：

1. **merchant** コンテナが起動し `http://localhost:8000` でリッスン
2. **demo** コンテナが起動し、replay-safe フローを実行して終了

期待される出力：

```
demo-1      | ================================================================
demo-1      |   AgentPass Demo — replay-safe agent authentication
demo-1      | ================================================================
demo-1      |
demo-1      | [Step 1] Fetching merchant metadata...
demo-1      |   merchant_id : demo-merchant-001
demo-1      |   public_key  : a1b2c3d4e5f6a7b8c9d0e1f2...
demo-1      |   pricing     : 0.001 JPY  →  /v1/pay
demo-1      |
demo-1      | [Step 2] Loading agent private key from demo_keys.json...
demo-1      |   Agent public key     : a1b2c3d4e5f6a7b8c9d0e1f2...
demo-1      |   Matches merchant key : ✓ yes
demo-1      |
demo-1      | [Step 3] Issuing one-time JWT via issue_token()...
demo-1      |   token_id    : 3f7a2b91-...
demo-1      |   valid_until : 12:34:56Z UTC
demo-1      |   amount      : 0.001 JPY
demo-1      |   aud         : https://agentpass-demo.local/v1/pay
demo-1      |
demo-1      | [Step 4] Attempt 1 — first call with valid token (expect 200)...
demo-1      |   ✓ HTTP 200: {'status': 'ok', 'agent_id': 'demo-agent-001', ...}
demo-1      |
demo-1      | [Step 5] Attempt 2 — replaying the same token (expect 403 REPLAY_ATTACK)...
demo-1      |   ✓ HTTP 403: {'error_code': 'REPLAY_ATTACK', 'detail': 'Token already used ...'}
demo-1      |
demo-1      | [Step 6] Attempt 3 — issuing a fresh token (new JTI, expect 200)...
demo-1      |   ✓ HTTP 200: {'status': 'ok', 'agent_id': 'demo-agent-001', ...}
demo-1      |
demo-1      | ================================================================
demo-1      |   DEMO RESULT: ALL STEPS PASSED
demo-1      |
demo-1      |   ✓ Step 1  Merchant metadata fetched
demo-1      |   ✓ Step 2  Agent private key loaded — public key matched
demo-1      |   ✓ Step 3  One-time JWT issued (Ed25519 signed)
demo-1      |   ✓ Step 4  First call granted   (HTTP 200)
demo-1      |   ✓ Step 5  Replay blocked       (HTTP 403 REPLAY_ATTACK)
demo-1      |   ✓ Step 6  Fresh token granted  (HTTP 200)
demo-1      |
demo-1      |   AgentPass is replay-safe: each token can only be used once.
demo-1      | ================================================================
```

---

## Quick Start (ローカル / Docker なし)

```bash
pip install agentpass-ai uvicorn
```

> **Note:** Install package: `agentpass-ai` / Import package: `agentpass`

```bash
# Terminal 1
python examples/merchant_api.py
```

```bash
# Terminal 2
python examples/agent_client.py
```

---

## What You're Seeing

### Step 4 → HTTP 200 (正常認証)

有効な Ed25519 署名済み JWT を送信。

- 署名 ✓ — エージェントの秘密鍵で署名、公開鍵で検証
- `aud` ✓ — `https://agentpass-demo.local/v1/pay` がリクエスト先 URL と一致
- `exp` ✓ — 有効期限内
- `jti` ✓ — 未使用の一意 ID → `AnomalyDetector` が記録

### Step 5 → HTTP 403 REPLAY_ATTACK

**同じトークンを再送信**（リプレイ攻撃）。

- `AnomalyDetector` が `jti` の重複を検知し即座に拒否
- トークンを傍受しても再利用できない

### Step 6 → HTTP 200 (新しいトークン)

新しい `jti` を持つトークンを発行して再送信。

- 正常通過 — リプレイ検知は他のトークンに影響しない

---

## Files

```
examples/
├── merchant_api.py      FastAPI merchant server (verify_token + AnomalyDetector)
├── agent_client.py      Agent client (issue_token + replay demo)
├── docker-compose.yml   Two-service demo environment
├── Dockerfile           python:3.13-slim image with agentpass installed
├── .env.example         Environment variable reference
└── README.md            このファイル
```

### merchant_api.py

起動時に Ed25519 鍵ペアを生成し `examples/keys/demo_keys.json` に保存します。

| エンドポイント | 説明 |
|---|---|
| `GET /.well-known/agentpass.json` | エージェントが公開鍵を取得する発見エンドポイント |
| `GET /health` | Docker ヘルスチェック用 |
| `GET /v1/pay` | AgentPass トークン必須の保護エンドポイント |

### agent_client.py

1. `/.well-known/agentpass.json` から公開鍵と価格を取得
2. `demo_keys.json` から秘密鍵を読み込む
3. `issue_token()` で使い捨て JWT を発行
4. `/v1/pay` を呼び出し（正常 → リプレイ → 新トークン）

---

## Keypair Note

> **Demo simplification:** merchant と agent が同じ鍵ペアを共有します。
>
> 本番では:
> - **エージェント**が独自の鍵ペアを生成・保有
> - **加盟店**はエージェントの公開鍵のみを `agentpass.json` に登録
> - 秘密鍵は加盟店に渡さない

`examples/keys/demo_keys.json` は `.gitignore` 済みです。

---

## Architecture

```
┌─────────────────────────────────────────────┐
│  merchant_api.py (FastAPI)                  │
│                                             │
│  /.well-known/agentpass.json                │
│    └─▶ { public_key: "a1b2c3..." }          │
│                                             │
│  /v1/pay                                    │
│    ├─▶ verify_token(token, pub_key, aud)    │
│    │     Ed25519署名 + aud + exp 検証       │
│    └─▶ AnomalyDetector.is_replay_attack()  │
│          jti 重複チェック → 403 on replay   │
└─────────────────────────────────────────────┘
          ▲  Authorization: AgentPass <JWT>
          │
┌─────────────────────────────────────────────┐
│  agent_client.py                            │
│                                             │
│  issue_token(TokenRequest, private_key)     │
│    └─▶ Ed25519署名付き JWT (jti 一意)        │
└─────────────────────────────────────────────┘
```

---

## Error Reference

| HTTP | `error_code` | 原因 |
|------|-------------|------|
| 400 | `INVALID_PAYLOAD` | 署名不一致 / 必須クレーム欠如 |
| 401 | `INVALID_PAYLOAD` | Authorization ヘッダー欠如 / スキーム誤り |
| 401 | `TOKEN_EXPIRED` | JWT の `exp` 超過 |
| 403 | `DESTINATION_MISMATCH` | `aud` が要求 URL と不一致 |
| 403 | `REPLAY_ATTACK` | 同一 JTI のトークンを再送信 |

---

## Next Steps

| やりたいこと | 参照 |
|---|---|
| ASGI ミドルウェアとして組み込む | メインの [README](../README.md#asgi-middleware-setup) |
| テストを実行する | `pytest` (263 tests) |
| 予算制限・レート制限を追加する | `CircuitBreaker` クラス |
| 信用スコアを組み込む | `CreditScorer` クラス |
