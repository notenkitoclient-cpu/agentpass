# AgentPass API Specification

> 現実装との整合性を保つ仕様書。  
> ✅ = 実装済み | 📋 = 設計済み未実装 | 🔭 = 構想

---

## Authorization Header

すべての保護エンドポイントに必須。スキームは大文字小文字を厳格に区別する。

```
Authorization: AgentPass <JWT>
```

**拒否されるスキーム（→ 401）:** `Bearer`, `Basic`, `agentpass`（小文字）, 空文字

---

## Token Payload ✅

EdDSA（Ed25519）署名付き JWT。

```json
{
  "sub": "agent-7f3a-...",
  "iss": "myagent.example.com",
  "aud": "https://api.merchant.com/v1/pay",
  "iat": 1747123456,
  "exp": 1747123516,
  "jti": "550e8400-e29b-41d4-a716-446655440000",
  "amt": 0.001,
  "cur": "JPY",
  "agp": "1"
}
```

| クレーム | 型 | 説明 | 制約 |
|---------|-----|------|------|
| `sub` | string | エージェント識別子 | 必須 |
| `iss` | string | 公開鍵取得元ドメイン（スキームなし） | 必須 |
| `aud` | string | 宛先 URL（完全一致） | 必須・HTTPS |
| `iat` | integer | 発行時刻（Unix秒） | 必須 |
| `exp` | integer | 有効期限（Unix秒） | 必須・最大 iat+300 |
| `jti` | string | 使い捨てID（UUID v4推奨） | 必須・再利用不可 |
| `amt` | float | 支払い額 | 必須・> 0・≤ 10.00 |
| `cur` | string | 通貨コード | 必須・現在 `"JPY"` のみ |
| `agp` | string | AgentPass プロトコルバージョン | 必須・現在 `"1"` |

---

## Merchant Metadata ✅

`https://{iss}/.well-known/agentpass.json` から自律取得。

```json
{
  "agentpass_version": "1.0.0",
  "merchant_id": "550e8400-e29b-41d4-a716-446655440001",
  "public_key": "a1b2c3d4e5f6...（64桁 HEX = Ed25519 32バイト）",
  "pricing": [
    { "endpoint": "/v1/pay", "price_per_token": 0.001 }
  ]
}
```

| フィールド | 型 | 説明 |
|---|---|---|
| `agentpass_version` | string | スキーマバージョン（現在 `"1.0.0"`） |
| `merchant_id` | string | 加盟店 UUID |
| `public_key` | string | Ed25519 公開鍵（64桁 HEX / 32バイト） |
| `pricing[].endpoint` | string | エンドポイントパス |
| `pricing[].price_per_token` | float | トークン単価（JPY） |

**⚠️ 注意:** `public_key` は HEX 文字列（base64url ではない）

---

## Error Response Format ✅

```json
{
  "error_code": "REPLAY_ATTACK",
  "message": "Token 'jti-xxx' has already been used",
  "http_status": 403
}
```

### Error Code 一覧

| HTTP | `error_code` | 発生条件 |
|------|-------------|---------|
| 400 | `INVALID_PAYLOAD` | JWT 形式不正・署名不一致・必須クレーム欠如 |
| 401 | `INVALID_PAYLOAD` | Authorization ヘッダー欠如・スキーム誤り |
| 401 | `TOKEN_EXPIRED` | `exp` 超過 |
| 403 | `DESTINATION_MISMATCH` | `aud` ≠ リクエスト URL |
| 403 | `REPLAY_ATTACK` | 同一 `jti` の再送 |
| 429 | `BUDGET_EXCEEDED` | 1分間の累積消費額超過・単一額超過 |
| 429 | `RATE_LIMITED` | 1分間のリクエスト数超過 |
| 503 | `MERCHANT_UNVERIFIED` | `agentpass.json` 取得失敗（DNS・HTTP・スキーマ） |

---

## Rate Limiting (CircuitBreaker) ✅

| 制限 | デフォルト値 | 設定可能 |
|------|-------------|---------|
| 単一トランザクション上限 | 10.00 JPY | `CircuitBreaker(max_single_transaction=...)` |
| 累積消費上限 | 0.10 JPY / 60秒 | `CircuitBreaker(max_budget_per_minute=...)` |
| 累積リクエスト上限 | 100 回 / 60秒 | `CircuitBreaker(max_requests_per_minute=...)` |
| ウィンドウサイズ | 60 秒（固定） | 変更不可 |

制限超過時は **トークンを記録せず** に例外を送出する（原子的操作）。

---

## AgentPassCrawler Constraints ✅

| 制約 | デフォルト値 | 設定可能 |
|------|-------------|---------|
| レスポンス上限 | 1,048,576 bytes (1MB) | `AgentPassCrawler(max_bytes=...)` |
| タイムアウト（接続・読み取り） | 5.0 秒 | `AgentPassCrawler(timeout=...)` |
| TTL キャッシュ | 3600 秒 | `AgentPassCrawler(ttl_seconds=...)` |
| 強制再取得 | `False` | `fetch_merchant_metadata(domain, force_refresh=True)` |

---

## Token Issuance API (SDK) ✅

```python
from agentpass import TokenRequest, issue_token, generate_keypair, CircuitBreaker

# キーペア生成（開発・テスト用）
private_key, public_key = generate_keypair()

# サーキットブレーカー（オプション）
cb = CircuitBreaker(
    max_budget_per_minute=0.10,
    max_requests_per_minute=100,
    max_single_transaction=10.00,
)

# トークン発行
req = TokenRequest(
    agent_id="agent-7f3a",
    destination_url="https://api.merchant.com/v1/pay",   # HTTPS 必須
    amount_requested=0.001,                                # JPY
    purpose="data query",                                  # ≤ 128 文字
    expires_in_seconds=60,                                 # 1〜300
)
issued = issue_token(req, private_key, circuit_breaker=cb)
# issued.token      : JWT 文字列
# issued.token_id   : jti（UUID）
# issued.valid_until: datetime（UTC）
```

---

## Token Verification API (SDK) ✅

```python
from agentpass import verify_token, VerificationError

try:
    claims = verify_token(token_str, public_key, merchant_url)
    # claims.agent_id       : str (sub)
    # claims.destination_url: str (aud)
    # claims.amount         : float (amt)
    # claims.currency       : str (cur)
    # claims.token_id       : str (jti)
    # claims.issued_at      : int (iat)
    # claims.expires_at     : int (exp)
except VerificationError as e:
    print(e.http_status, e.error_code)
```

---

## Future API Endpoints 📋🔭

> **Status: 未実装（Wave 2 以降）**

```
GET  /v1/agents/{agent_id}/score       # 信用スコア取得
GET  /v1/agents/{agent_id}/history     # トランザクション履歴
POST /v1/agents/{agent_id}/report      # 不正報告
GET  /v1/merchants/{merchant_id}/stats # 加盟店統計
```

---

## TODO

- [ ] OpenAPI (Swagger) スキーマ生成（`fastapi`の自動生成を活用）
- [ ] `cur` クレームのマルチ通貨対応（Wave 2）
- [ ] `/v1/agents/{id}/score` エンドポイント設計
- [ ] レート制限ヘッダー（`X-RateLimit-*`）のレスポンスへの追加
