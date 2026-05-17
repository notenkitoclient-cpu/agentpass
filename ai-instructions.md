# AgentPass — AI Agent Instructions (Machine-Readable Spec)

> **FOR AI AGENTS:** This document is your single source of truth for AgentPass integration.
> Read this entirely before making any API calls or code decisions.

## 1. What AgentPass Does

AgentPass issues **single-use, cryptographically-signed tokens** that authorize an AI agent to make a specific purchase at a specific URL, within a specific budget, for a limited time window.

**You (the AI agent) must:**
1. Request a token from AgentPass Core API before purchasing anything
2. Attach the token as an HTTP Authorization header when calling the merchant
3. Never reuse a token — each transaction requires a new one
4. Never exceed the `max_amount_per_minute` limit

---

## 2. Token Schema (Strict — Do Not Deviate)

### 2.1 Token Request Payload (Agent → AgentPass)

```json
{
  "agent_id": "string (UUID v4, your identity)",
  "destination_url": "string (exact URL you intend to call, no wildcards)",
  "amount_requested": "number (in JPY, e.g. 0.01)",
  "currency": "JPY",
  "purpose": "string (human-readable reason, max 128 chars)",
  "expires_in_seconds": "integer (max: 300, recommended: 60)"
}
```

### 2.2 Token Response Payload (AgentPass → Agent)

```json
{
  "token": "string (JWT, signed with EdDSA/Ed25519)",
  "token_id": "string (UUID v4, for audit logs)",
  "valid_until": "string (ISO 8601 timestamp)",
  "destination_url": "string (echoed back for verification)",
  "max_amount": "number (JPY)",
  "agent_id": "string (echoed back)",
  "circuit_breaker": {
    "budget_remaining_1min": "number (JPY remaining in this minute's budget)",
    "requests_remaining_1min": "integer"
  }
}
```

### 2.3 JWT Claims (inside the token)

```json
{
  "sub": "agent_id",
  "aud": "destination_url",
  "iat": "unix timestamp (issued at)",
  "exp": "unix timestamp (expires)",
  "jti": "token_id (JWT ID, for replay prevention)",
  "amt": "amount_requested (number)",
  "cur": "JPY",
  "agp": "1" (AgentPass version marker)
}
```

---

## 3. Circuit Breaker Rules (Hard Limits — Non-Negotiable)

The following limits are enforced server-side and cannot be overridden by the agent:

| Limit | Default Value | Configurable by? |
|---|---|---|
| Max spend per minute per agent | 0.10 JPY | Parent/Owner only |
| Max requests per minute per agent | 100 | Parent/Owner only |
| Token max lifetime | 300 seconds | Requester (up to max) |
| Max single-transaction amount | 10.00 JPY | Parent/Owner only |

**If you exceed these limits, your token will be rejected with HTTP 429 and the parent will be notified.**

---

## 4. Merchant Integration (`agentpass.json`)

Merchants place this file at: `https://example.com/.well-known/agentpass.json`

```json
{
  "agentpass_version": "1.0",
  "merchant_id": "string (UUID v4)",
  "merchant_name": "string",
  "public_key": "string (Ed25519 public key, base64url encoded)",
  "accepted_currencies": ["JPY"],
  "pricing": [
    {
      "endpoint": "/api/data/search",
      "price_per_request": 0.001,
      "currency": "JPY",
      "description": "Search endpoint, per query"
    }
  ],
  "settlement_address": "string (payment destination identifier)",
  "min_agent_credit_score": 0.5
}
```

**As an agent, before purchasing:**
1. Fetch `/.well-known/agentpass.json` from the target domain
2. Verify `agentpass_version` is supported
3. Check `min_agent_credit_score` against your current AgentID score
4. Use the `pricing` array to calculate the required `amount_requested`

---

## 5. Authorization Header Format

When calling a merchant endpoint with an AgentPass token:

```http
GET /api/data/search?q=example HTTP/1.1
Host: merchant.example.com
Authorization: AgentPass <token>
X-AgentPass-TokenID: <token_id>
X-AgentPass-AgentID: <agent_id>
```

---

## 6. AgentID (Authentication & Credit Score)

Your AgentID is derived from:
- Parent's KYC verification status (0 = unverified, 1 = fully verified)
- Your historical error rate (lower is better)
- Total successful transactions
- Account age

**Credit Score Range:** 0.0 (untrusted) to 1.0 (fully trusted)

New agents start at **0.3**. Score increases with successful, on-budget transactions.

---

## 7. Error Codes

| HTTP Status | Code | Meaning | Your Action |
|---|---|---|---|
| 400 | `INVALID_PAYLOAD` | Malformed request | Fix your request schema |
| 401 | `TOKEN_EXPIRED` | Token past `valid_until` | Request a new token |
| 403 | `DESTINATION_MISMATCH` | Token used at wrong URL | Use token only at `destination_url` |
| 429 | `BUDGET_EXCEEDED` | Circuit breaker triggered | Wait until next minute window |
| 429 | `RATE_LIMITED` | Too many requests | Back off exponentially |
| 503 | `MERCHANT_UNVERIFIED` | Merchant has no `agentpass.json` | Do not proceed |

---

## 8. What You Must Never Do

- Never store a token for reuse — request a fresh one for every transaction
- Never call a URL that differs from `destination_url` in your token
- Never attempt to modify token payload — the signature will invalidate it
- Never exceed your budget — circuit breaker data in responses is authoritative
- Never skip the `agentpass.json` check before a purchase

---

## 9. Quick Implementation Checklist

```
[ ] Read agentpass.json from target domain
[ ] Verify merchant public key
[ ] Calculate required amount from pricing array
[ ] POST /token to AgentPass Core API with exact destination_url
[ ] Receive token, verify valid_until is in the future
[ ] Attach Authorization: AgentPass <token> header
[ ] Call merchant endpoint
[ ] Log transaction result (success/failure) for credit score calculation
[ ] Discard token — never reuse
```

---

*AgentPass Spec Version: 0.1-alpha | Last updated: 2026-05-16*
