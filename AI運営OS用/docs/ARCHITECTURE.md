# AgentPass Architecture

> ✅ = 実装済み | 🔄 = 構築中 | 🔭 = 将来構想

---

## System Overview ✅

```mermaid
graph TB
    subgraph Agent["AI Agent"]
        AK[Ed25519 Private Key]
        TI[issue_token]
        AK --> TI
    end

    subgraph Transport["HTTPS Transport"]
        H["Authorization: AgentPass <JWT>"]
        TI --> H
    end

    subgraph Middleware["AuthorizationMiddleware ✅"]
        direction TB
        P1[1. Header Parse]
        P2[2. JWT unverified decode → iss]
        P3[3. AgentPassCrawler]
        P4[4. TokenVerifier]
        P5[5. AnomalyDetector]
        P6[6. Bind agent_claims]
        P1 --> P2 --> P3 --> P4 --> P5 --> P6
    end

    subgraph Crawler["AgentPassCrawler ✅"]
        C1[SSRF Check]
        C2[HTTP Stream ≤ 1MB]
        C3[JSON + Pydantic Validate]
        C4[TTL Cache 3600s]
        C1 --> C2 --> C3 --> C4
    end

    subgraph Merchant["Merchant Server"]
        MJ["/.well-known/agentpass.json"]
        EP["/v1/endpoint"]
    end

    H --> Middleware
    P3 --> Crawler
    Crawler --> MJ
    P6 --> EP
```

---

## Token Flow ✅

```mermaid
sequenceDiagram
    participant A as AI Agent
    participant M as AuthorizationMiddleware
    participant C as AgentPassCrawler
    participant WK as /.well-known/agentpass.json
    participant AD as AnomalyDetector
    participant E as Merchant Endpoint

    A->>M: POST /v1/pay<br/>Authorization: AgentPass <JWT>
    M->>M: Parse header, extract iss from JWT (no verify)
    M->>C: fetch_merchant_metadata(iss)
    C->>C: SSRF check (DNS resolve → block private IP)
    C->>WK: GET https://{iss}/.well-known/agentpass.json
    WK-->>C: {public_key, pricing, ...}
    C-->>M: MerchantMetadata
    M->>M: verify_token(jwt, public_key, merchant_url)
    Note over M: 1. Ed25519 signature<br/>2. exp (not expired)<br/>3. aud == request URL
    M->>AD: is_replay_attack(jti, exp)
    AD-->>M: False (first use)
    M->>E: dispatch(request) with agent_claims bound
    E-->>A: 200 OK {"agent_id": ..., "amount": ...}
```

---

## Token Structure ✅

```
Header:
  alg: EdDSA
  typ: JWT

Payload:
  sub:  <agent_id>          # エージェント識別子
  iss:  <domain>             # 公開鍵取得元ドメイン
  aud:  <full URL>           # 宛先 URL（完全一致検証）
  iat:  <unix timestamp>     # 発行時刻
  exp:  <unix timestamp>     # 有効期限（最大300秒）
  jti:  <uuid4>              # 使い捨てID（リプレイ防止）
  amt:  <float JPY>          # 支払い額
  cur:  "JPY"                # 通貨（現在 JPY のみ）
  agp:  "1"                  # AgentPass プロトコルバージョン

Signature:
  Ed25519(private_key, header.payload)
```

---

## AgentID Derivation ✅

```mermaid
graph LR
    PK[Ed25519 Public Key\n32 bytes raw] --> SHA[SHA-256 Hash\n32 bytes]
    SHA --> FIRST[First 16 bytes]
    FIRST --> UUID[UUID string\ne.g. 550e8400-e29b-41d4-a716-446655440000]
```

**実装:** `src/identity/agent_signer.py`
```python
def derive_agent_id(public_key_bytes: bytes) -> str:
    digest = hashlib.sha256(public_key_bytes).digest()
    return str(uuid.UUID(bytes=digest[:16]))
```

**特性:** 決定論的・同一公開鍵から常に同一UUID・衝突不可

---

## Circuit Breaker ✅

```mermaid
graph TB
    REQ[Token Request] --> ST[Single Transaction Check]
    ST -->|amount > 10 JPY| BE1[BudgetExceededError 429]
    ST -->|OK| BUD[Budget Check\ncumulative ≤ 0.10 JPY/min]
    BUD -->|exceeded| BE2[BudgetExceededError 429]
    BUD -->|OK| RATE[Rate Check\n≤ 100 req/min]
    RATE -->|exceeded| RL[RateLimitedError 429]
    RATE -->|OK| REC[Record + Return Status]

    subgraph Window["60s Sliding Window (per agent_id)"]
        TS[(timestamps + amounts)]
        REC --> TS
    end
```

**デフォルト制限:**

| 制限 | 値 |
|------|-----|
| 単一トランザクション上限 | 10.00 JPY |
| 累積消費上限 | 0.10 JPY / 60秒 |
| 累積リクエスト上限 | 100 回 / 60秒 |
| スライディングウィンドウ | 60 秒 |

---

## SSRF Protection ✅

```mermaid
graph LR
    DOMAIN[domain name] --> DNS[socket.gethostbyname_ex]
    DNS -->|gaierror| BLOCK1[ValueError: SSRF Protection]
    DNS -->|empty list| BLOCK2[ValueError: SSRF Protection]
    DNS -->|IP list| CHECK{ipaddress check}
    CHECK -->|is_private OR is_loopback\nOR is_link_local OR is_reserved\nOR is_multicast OR is_unspecified| BLOCK3[ValueError: SSRF Protection]
    CHECK -->|unparseable| BLOCK4[ValueError: SSRF Protection]
    CHECK -->|all public| PASS[Proceed to HTTP]
```

**⚠️ Python 3.14 注意:** `203.0.113.0/24`（RFC 5737 TEST-NET-3）は `is_private=True`  
テスト用モック公開IPは必ず `8.8.8.8` を使用。

---

## Merchant Verification ✅

```mermaid
graph TB
    FETCH["AgentPassCrawler.fetch_merchant_metadata(domain)"]
    FETCH --> CACHE{TTL Cache\n3600s}
    CACHE -->|HIT| RETURN[Return MerchantMetadata]
    CACHE -->|MISS or force_refresh| SSRF[SSRF Check]
    SSRF --> STREAM["HTTP Stream\n≤ 1MB chunked"]
    STREAM -->|> 1MB| ERR1[ValueError: Security Boundary Exceeded]
    STREAM --> JSON[JSON Parse]
    JSON -->|invalid| ERR2[ValueError: Invalid JSON]
    JSON -->|not dict| ERR3[ValueError: must be JSON object]
    JSON --> SCHEMA[Pydantic MerchantMetadata validate]
    SCHEMA -->|missing field| ERR4[ValueError: Schema validation failed]
    SCHEMA --> WRITE[Cache Write]
    WRITE --> RETURN
```

---

## Replay Attack Defense ✅

```mermaid
graph LR
    JTI[jti claim] --> AD[AnomalyDetector]
    AD --> GC[GC: remove expired JTIs\nwhere exp < now]
    GC --> CHECK{jti in used_jtis?}
    CHECK -->|YES| REPLAY[403 REPLAY_ATTACK]
    CHECK -->|NO| RECORD[Record jti → exp]
    RECORD --> PASS[Pass to endpoint]
```

---

## Package Structure ✅

```
src/
├── agentpass/          # 公開 API（pip install agentpass）
│   └── __init__.py     # 22シンボル flat export
├── core/               # 実装層
│   ├── token_issuer.py
│   ├── token_verifier.py
│   ├── circuit_breaker.py
│   ├── agentpass_crawler.py
│   ├── authorization_middleware.py
│   └── anomaly_detector.py
├── identity/           # アイデンティティ層
│   ├── agent_signer.py
│   └── credit_scorer.py
└── merchant/           # 旧設計（非推奨・参照専用）
```

---

## Sandbox Architecture 🔄

> **Status: 進行中**

```
TODO: Sandbox 構成図をここに追加
- 本番 API を呼び出さない隔離環境
- respx による httpx モック
- FakeTime による時刻制御
- 実験ログ → EXPERIMENT_LOG.md
```

---

## Future Architecture 🔭

```
TODO: Wave 2〜4 の技術アーキテクチャ
- AgentID レピュテーション DB
- 信用スコア公開 API
- M2M 清算レイヤー
- DID 統合
```
