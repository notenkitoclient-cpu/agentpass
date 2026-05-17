# AgentPass Decisions Log

> Architectural and operational decisions for the AgentPass project.
> AI agents reading this file should treat ACTIVE decisions as hard constraints.
> SUPERSEDED decisions record why earlier approaches were changed.
>
> Status values: `ACTIVE` | `SUPERSEDED` | `UNDER_REVIEW`

---

## Decision Format

Each entry contains:

| Field | Description |
|-------|-------------|
| **ID** | `DEC-NNN` — sequential, never reused |
| **Date** | ISO date of the decision |
| **Status** | ACTIVE / SUPERSEDED / UNDER_REVIEW |
| **Context** | What situation or tension prompted this decision |
| **Decision** | What was decided, stated precisely |
| **Why** | Primary reasons — link to experiments or incidents where possible |
| **Tradeoffs** | Known costs and risks accepted |
| **Future Revisit Trigger** | Specific condition that should reopen this decision |

---

## DEC-001: Replay-First Architecture

- **Date**: 2026-05-16
- **Status**: ACTIVE

### Context

Stateless JWT-based auth systems are vulnerable to replay attacks: a token intercepted in transit can be reused indefinitely. For AI-to-AI communication, where agents operate autonomously without human review of each call, a replayed token can drain budgets, impersonate agents, or trigger duplicate operations silently.

### Decision

Every token has a unique `jti` (JWT ID) registered on first use. Any reuse of the same `jti` is immediately rejected with HTTP 403 `REPLAY_ATTACK`, regardless of signature validity or expiry.

### Why

- Replay attacks are the most common active attack against stateless auth systems
- Solving replay first defines the threat model boundary for all other features
- `AnomalyDetector` with TTL-based JTI tracking handles both replay detection and garbage collection in a single component
- 7 e2e tests (`test_agentpass_ecosystem.py`) verify the full issuance → verify → replay-blocked cycle

### Tradeoffs

| Accepted Cost | Notes |
|---------------|-------|
| `AnomalyDetector` is in-memory | Replay protection is per-process; multi-instance deployments need a shared store (Redis, etc.) |
| TTL-based GC means very old JTIs can eventually be reused | TTL is set to token `exp` — tokens expire before their JTI is eligible for GC |
| Adds latency on every request | JTI lookup is O(1) hash set; latency impact is negligible |

### Future Revisit Trigger

When multi-instance merchant deployments are required — at that point, `AnomalyDetector` must be backed by a distributed store, not in-memory.

---

## DEC-002: tests = protocol law

- **Date**: 2026-05-16
- **Status**: ACTIVE

### Context

During early development, a refactoring reduced the test count from 179 → 147. This silently dropped coverage to 89% and removed tests for SSRF edge cases that are security-critical. The coverage gap was only discovered by running `pytest --cov` explicitly.

### Decision

The test suite floor is **never reduced** without human approval. Tests may be added freely. A test may only be removed if:
1. The code it tests has been deleted, AND
2. A human explicitly approves the removal in a PR description

AI agents must never delete tests to make the suite "cleaner." The current floor is 263 tests.

### Why

- Tests encode security guarantees: SSRF defense, replay detection, Ed25519 signature verification, `aud` destination locking. Removing a test removes a guarantee.
- The 179→147 incident created a coverage gap that required 6 additional tests to restore. The cost of re-discovering a gap in production is far higher.
- CI enforces the floor: if fewer tests run, the pipeline fails.

### Tradeoffs

| Accepted Cost | Notes |
|---------------|-------|
| Test suite grows over time | Some coverage overlap is acceptable — redundancy in security tests is a feature |
| Refactoring is constrained | Tests must be updated alongside code changes, not deleted |
| Slow test suites in future | If suite exceeds 1000 tests, split into unit/integration/e2e CI stages |

### Future Revisit Trigger

If test count exceeds 500 and CI runtime exceeds 5 minutes — at that point, introduce test categorization with parallel execution rather than reducing coverage.

---

## DEC-003: Experiment-First Development

- **Date**: 2026-05-17
- **Status**: ACTIVE

### Context

After Wave 1 core (Ed25519 JWT, SSRF defense, ASGI middleware, 153 tests) was complete, the question was whether to add features (multi-currency, revocation, dashboard) or validate what was already built.

### Decision

No new core features ship until sandbox experiments validate the existing feature set. Each experiment follows the structure: hypothesis → setup → result → learnings → next action. Results are logged in `AI運営OS用/docs/EXPERIMENT_LOG.md`.

### Why

- Building features before validating usage is waste — the sandbox has already revealed issues (module identity split, threading race conditions) that unit tests missed
- Experiments are low-cost and reversible; feature work is expensive to undo
- EXP-005b discovered that `from src.core.xxx` and `from core.xxx` produce different Python class objects when `pythonpath = ["src", "."]` — an issue invisible in unit tests that would have broken multi-threaded deployments silently

### Tradeoffs

| Accepted Cost | Notes |
|---------------|-------|
| Delays feature development | Acceptable: correctness before completeness |
| Sandbox results may not generalize | Production data will eventually supersede sandbox findings |
| Experiment overhead | Logging and structure add ~10% time per experiment |

### Future Revisit Trigger

After 10+ successful experiments with real AI agent deployments providing production traffic data — at that point, shift toward feature development driven by measured usage patterns.

---

## DEC-004: Sandbox Verification Before Public Distribution

- **Date**: 2026-05-17
- **Status**: ACTIVE

### Context

AgentPass is security-critical infrastructure. Publishing a package to PyPI before verifying behavior under realistic adversarial conditions (replay burst, concurrent JTI collision, keypair isolation) could expose early adopters to silent vulnerabilities.

### Decision

A minimum of 5 sandbox experiments covering the core security boundaries must complete before production PyPI publication:
- EXP-004: Full purchase flow (baseline)
- EXP-005a: Budget control (HTTP 402)
- EXP-005b: JTI collision under concurrency
- EXP-006: Replay burst detection and freeze
- EXP-005c: Multi-agent keypair isolation

All 5 are now complete. This condition is satisfied.

### Why

- EXP-005b found a real concurrency bug (threading.Lock missing on JTI registration) that unit tests did not catch
- EXP-006 validated that the `FreezeLayer` wrapper correctly isolates burst-detection policy without modifying `SandboxVerifier`
- EXP-005c confirmed that compromised-key revocation does not affect other agents' keys

### Tradeoffs

| Accepted Cost | Notes |
|---------------|-------|
| Delayed public release | Sandbox phase added ~2 weeks before PyPI publish |
| Sandbox ≠ production | Some production edge cases (e.g., network partitions) cannot be simulated in sandbox |

### Future Revisit Trigger

When production deployments provide traffic data that contradicts sandbox findings — update or supersede this decision with production-derived constraints.

---

## DEC-005: TestPyPI Before Production PyPI

- **Date**: 2026-05-17
- **Status**: ACTIVE

### Context

Once published to PyPI, a specific version cannot be deleted (only yanked). A broken package — even briefly available — damages trust. The issue `ModuleNotFoundError: No module named 'src'` was discovered during TestPyPI external install verification; it was invisible in all 263 tests because pytest's `pythonpath = ["src", "."]` masks the problem.

### Decision

Every release must pass the full TestPyPI validation sequence before production publish:

```bash
python -m build
twine check dist/*
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ agentpass==VERSION
python -c "from agentpass import issue_token; print('ok')"
```

Failure at any step blocks the production release.

### Why

- The `src.` import bug (`from src.core.xxx import` instead of `from core.xxx import`) survived 263 tests and was only caught by an actual external install. The gap exists because pytest adds `src/` to `sys.path`; `pip install` does not.
- A broken PyPI release cannot be undone — it can only be yanked, which breaks downstream `pip install agentpass` until users update their version pin.

### Tradeoffs

| Accepted Cost | Notes |
|---------------|-------|
| Requires TestPyPI account and API token | One-time setup cost |
| TestPyPI is occasionally slow or unavailable | Non-blocking: retry after 24h |
| Adds ~5 minutes to release process | Acceptable given the cost of a broken production release |

### Future Revisit Trigger

When a CI pipeline automatically runs the TestPyPI validation sequence on every release tag — manual verification can then be replaced by the CI gate.

---

## DEC-006: External Install Verification Required Before Launch

- **Date**: 2026-05-17
- **Status**: ACTIVE

### Context

`pytest` runs with `pythonpath = ["src", "."]` (from `pyproject.toml`). This puts both `src/` and `.` on `sys.path`, making both `from core.xxx import` and `from src.core.xxx import` resolve. After `pip install agentpass`, only bare package names (`core`, `agentpass`, `identity`) are on the path — `src` does not exist.

The `src.` prefix in 23 source and test files caused `ModuleNotFoundError` for every external user, despite 263 tests passing green.

### Decision

Before any public distribution, verify with a clean environment:
1. `pip install agentpass` (from TestPyPI or production)
2. `python -c "from agentpass import issue_token, AuthorizationMiddleware; print('ok')"`
3. `grep -r "from src\." src tests` must return 0 results

Condition 3 is now enforced as a post-release lint check.

### Why

- The `src.` import bug was invisible in the development environment because of pytest's `pythonpath` setting — a well-intentioned config that masks a real distribution problem
- External install is the only environment that mirrors what a `pip install agentpass` user actually sees

### Tradeoffs

| Accepted Cost | Notes |
|---------------|-------|
| Requires a separate clean virtualenv for testing | 2-minute setup; worth the insurance |
| `grep` check must be added to CI | Not yet automated — currently manual |

### Future Revisit Trigger

When `grep -r "from src\." src tests` is added as a CI step that blocks merges — manual verification can be removed.

---

## DEC-007: Public/Private Strategy Separation

- **Date**: 2026-05-17
- **Status**: ACTIVE

### Context

AgentPass has both a technical identity (replay-safe M2M auth middleware) and a business strategy (Wave2 credit network, Wave3 M2M clearing). Early README drafts mixed both: "ゴールドラッシュのスコップ屋" language and Wave2/Wave3 roadmap appeared in the public OSS description.

### Decision

Public-facing documents (`README.md`, `SECURITY.md`, `docs/`) contain **only** technical content: what AgentPass does, how to install it, how to use it, what it protects against.

Business strategy, competitive positioning, Wave2/Wave3 roadmap, and internal KPIs live exclusively in `AI運営OS用/` and are not published.

### Why

- Mixing strategy with technical docs causes two distinct failures: (1) external developers see marketing language instead of technical facts; (2) confidential strategy becomes public inadvertently
- OSS trust is built on technical credibility, not business vision. Developers evaluate middleware by its security model and API quality, not by manifesto language.
- "AIエージェントが人間と同じように経済活動する時代に" is a founder's vision, not a user-facing technical statement.

### Tradeoffs

| Accepted Cost | Notes |
|---------------|-------|
| Less "story" in the public README | Technical credibility is more durable than narrative excitement |
| OSS community may not immediately understand the business vision | Intentional — vision should follow adoption, not precede it |
| Requires discipline to keep strategy documents out of the public tree | AI agents must be explicitly instructed to keep `AI運営OS用/` docs internal |

### Future Revisit Trigger

If AgentPass reaches a stage where public roadmap communication is strategically required (e.g., enterprise partnerships, funding announcements) — at that point, create a separate `ROADMAP.md` at the project root containing only committed, implemented features.

---

## DEC-008: ACTIVE TASK Singular Rule

- **Date**: 2026-05-17
- **Status**: ACTIVE

### Context

Multiple AI agents (Claude Code, ChatGPT, Codex, Gemini CLI) operate on the AgentPass project concurrently, often across separate sessions with no shared memory. Without a single source of truth for current work, agents make conflicting changes: updating the same file in contradictory ways, starting tasks that supersede each other, or reopening decisions that were already closed.

### Decision

`AI運営OS用/docs/MASTER_STATUS.md` always has exactly one `ACTIVE TASK`. New work proposals go to `TASK QUEUE`. An AI agent may not move a task from QUEUED to ACTIVE without human confirmation. Every session ends with either an ACTIVE TASK change or a QUEUE addition — never silent.

### Why

- AI agents have no persistent memory across sessions. MASTER_STATUS.md is the only shared state that survives context resets.
- Concurrent agents working on different tasks simultaneously produce merge conflicts and contradictory docs. This has happened: two agents edited `EXPERIMENT_LOG.md` in different sessions with incompatible assumptions.
- The singular ACTIVE TASK rule keeps the working set small enough for a human to review before each session.

### Tradeoffs

| Accepted Cost | Notes |
|---------------|-------|
| Slower parallel execution | Intentional: correctness over throughput for security-critical decisions |
| Bottleneck on human approval for task transitions | Human-in-the-loop is a feature, not a bug, for this project stage |
| TASK QUEUE can grow long | Queue entries are cheap; the bottleneck is execution, not planning |

### Future Revisit Trigger

When AI agent orchestration frameworks (multi-agent with atomic task locking, conflict detection, automated merge resolution) reach production maturity — at that point, the singular ACTIVE TASK constraint can be relaxed with tooling guarantees replacing the manual constraint.

---

## DEC-009: Wave2/Wave3 Kept Internal

- **Date**: 2026-05-17
- **Status**: ACTIVE

### Context

AgentPass Wave2 (agent credit score API, dynamic credit limits) and Wave3 (M2M clearing, exchange, liquidity pools) are unimplemented aspirational features. They appeared in the original public README under "3ホライゾン戦略." External developers reading the README encountered M2M bank language without any corresponding code, tests, or API.

### Decision

Wave2 and Wave3 content exists only in `AI運営OS用/docs/ROADMAP.md`. Public-facing documentation describes only features that are implemented, tested, and available in the current package version.

### Why

- Over-promising implemented capability is a credibility risk that compounds over time: each user who encounters a documented feature that doesn't exist becomes a lost adopter
- "M2M中央銀行" and "流動性プール" are meaningful long-term goals but are noise for a developer evaluating whether to use `pip install agentpass` today
- `agentpass/__init__.py` exports 22 symbols — those 22 symbols are the product; everything else is a roadmap item

### Tradeoffs

| Accepted Cost | Notes |
|---------------|-------|
| Reduced early narrative excitement | Technical credibility is more durable |
| Internal strategy documents not version-controlled publicly | `AI運営OS用/docs/` is committed to the private repo |
| OSS community may perceive AgentPass as narrower than intended | Correct perception — until Wave2 ships, AgentPass IS narrow. That is a strength for adoption. |

### Future Revisit Trigger

When Wave2 API (agent reputation score endpoint) is implemented, tested, and merged to main — add it to the public README with working code examples and verified test coverage. Do not add to public docs before then.

---

_Maintained by: Human founder + AI operating agents_
_AI agents: treat ACTIVE decisions as hard constraints. Propose changes via TASK QUEUE in MASTER_STATUS.md; do not modify ACTIVE decisions unilaterally._
