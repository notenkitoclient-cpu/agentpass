# CHANGELOG

> This file records all meaningful changes to the AgentPass project in reverse chronological order.
> AI agents reading this file can use it to understand what has changed, when, and why.
>
> Format: `[YYYY-MM-DD] Category: Description`
> Categories: `feat` / `fix` / `ci` / `docs` / `refactor` / `test` / `chore`

---

## [Unreleased]

_Changes merged to `main` but not yet released to PyPI._

---

## 2026-05-17

### ci: Add GitHub Actions pytest + coverage workflow

- **File**: `.github/workflows/ci.yml`
- **Trigger**: `push` / `pull_request` → `main`
- **Runtime**: Python 3.14 (`allow-prereleases: true`) on `ubuntu-latest`
- **Gates**:
  - `pytest --cov=src` — all 153 tests must pass
  - `coverage report --include="src/core/agentpass_crawler.py" --fail-under=100` — crawler coverage must be 100%
- **Artifact**: `coverage.xml` retained for 7 days
- **Intent**: Prevent regressions before any PR merges to `main`

---

## 2026-05-16

### test: Raise crawler coverage from 89% → 100%

- **File**: `tests/test_agentpass_crawler.py`
- **Added tests** (+6):
  - `test_ssrf_empty_ip_list` — DNS returns empty IP list
  - `test_ssrf_unparseable_ip_string` — DNS returns non-IP string
  - `test_network_error_raises_runtime_error` — `httpx.ConnectError` → `RuntimeError("Network error")`
  - `test_invalid_json_raises_value_error` — malformed bytes → `ValueError("Invalid JSON")`
  - `test_json_array_raises_value_error` — JSON array (not object) → `ValueError("must be a JSON object")`
  - `test_schema_validation_failure_raises_value_error` — missing required fields → `ValueError("Schema validation failed")`
- **Total tests**: 147 → 153

### docs: Create AI運営OS用/docs/ document suite

- **Files created** (9 files):
  - `README.md` — project overview for AI agents
  - `ROADMAP.md` — 3-horizon roadmap (Wave 1/2/3)
  - `BUSINESS_PLAN.md` — goldfish-shovel business model detail
  - `ARCHITECTURE.md` — system components and data flow
  - `API_SPEC.md` — agentpass.json schema and HTTP API
  - `AI_INSTRUCTIONS.md` — behavior protocol for AI operating agents
  - `TESTING_POLICY.md` — test rules (includes SSRF mock IP = 8.8.8.8 rule)
  - `EXPERIMENT_LOG.md` — EXP-001 through EXP-003 results
  - `CONTRIBUTING.md` — contribution guidelines
- **Intent**: Separate AI-native operational docs from code-level docs; enable ChatGPT / Claude Code / Codex / Gemini CLI to operate the project autonomously

### chore: Initial GitHub push and .gitignore merge

- **Remote**: `https://github.com/notenkitoclient-cpu/agentpass.git`
- **Branch**: `main`
- **Resolution**: GitHub's auto-generated 218-line Python `.gitignore` merged with local project-specific entries via `git pull --rebase origin main`
- **Added to .gitignore**: `.claude/`, macOS artifacts, cert files (`*.pem`, `*.key`, etc.), `*.sqlite3`, `.vscode/`, `.idea/`

### chore: PyPI packaging setup (v1.0.0-beta1)

- **File**: `pyproject.toml` — rewritten with `setuptools>=72`, src-layout, full dependency list
- **File**: `src/agentpass/__init__.py` — new public API entry point; exports 22 symbols
- **Import path**: `from agentpass import AuthorizationMiddleware, CircuitBreaker, ...`
- **Version**: `1.0.0-beta1`
- **Note**: Not yet published to PyPI

---

## [Historical — Week 1–4 Implementation]

_The following milestones were completed before this changelog was started._

### feat: Week 4 — AnomalyDetector (JTI replay defense)

- `src/core/anomaly_detector.py`
- JTI deduplication with GC; pluggable `_time_func` for deterministic testing
- Credit score integrated: `CreditScorer` returns 0–100

### feat: Week 3 — CircuitBreaker (budget / rate guard)

- `src/core/circuit_breaker.py`
- 60-second sliding window; defaults: 0.10 JPY/min, 100 req/min, 10.00 JPY single-token cap
- Raises `BudgetExceededError`, `RateLimitedError`, `CircuitBreakerError`

### feat: Week 2 — Token issuer / verifier (Ed25519 JWT)

- `src/core/token_issuer.py` — `issue_token()`, `generate_keypair()`
- `src/core/token_verifier.py` — `verify_token()`, typed `VerifiedClaims`
- Custom claims: `amt`, `cur`, `agp`
- Errors: `TokenExpiredError`, `DestinationMismatchError`, `InvalidPayloadError`

### feat: Week 1 — AgentPassCrawler (SSRF-safe metadata fetcher)

- `src/core/agentpass_crawler.py`
- 4 defensive layers: SSRF check → 1 MB stream limit → HTTP error handling → TTL cache
- `force_refresh=True` bypasses TTL cache
- Python 3.14 compatibility: SSRF mock IP must be `8.8.8.8` (RFC 5737 TEST-NET-3 = `is_private=True` in 3.14)

---

## Template for Future Entries

```markdown
## YYYY-MM-DD

### <category>: <title>

- **File(s)**: `path/to/file.py`
- **What changed**: one sentence
- **Why**: motivation or issue reference
- **Impact**: tests added/changed, API changes, breaking changes
```

---

_Maintained by: AI operating agents + human review_
_Format inspired by: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)_
