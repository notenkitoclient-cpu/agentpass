# DECISIONS

> Architectural and operational decisions made during the AgentPass project.
> AI agents reading this file should treat these decisions as standing constraints
> unless a newer decision explicitly supersedes one.
>
> Status values: `ACTIVE` / `SUPERSEDED` / `UNDER_REVIEW`

---

## Decision 001: Use ChatGPT Projects as the AgentPass Operations OS

- **Date**: 2026-05-16
- **Status**: ACTIVE
- **Decided by**: Human founder + Claude Code

### Context

AgentPass is being built by a solo founder operating with AI agents (ChatGPT, Claude Code, Codex, Gemini CLI) as development and operational partners. A persistent, shared context is needed so that any AI agent can pick up operational tasks without losing project memory.

### Decision

Use **ChatGPT Projects** as the primary persistent context layer ("AI Operations OS") for day-to-day operations, strategy, and decision logging.

### Why

- ChatGPT Projects persists conversation history across sessions — AI agents can read prior decisions without repeating discovery work
- Separates strategic/operational context (ChatGPT) from code-editing context (Claude Code sessions)
- Low friction: no infrastructure to maintain, no additional service accounts
- Compatible with the "goldfish-shovel" model — founder stays at strategy layer, AI agents handle execution

### Tradeoffs

| Pro | Con |
|-----|-----|
| Zero infra cost | Tied to OpenAI's platform availability |
| Persistent across AI sessions | Not version-controlled (can't `git diff`) |
| Any AI agent can read project state | Token limits constrain how much history is inline |
| Familiar chat interface | Requires discipline to keep records structured |

### Next Action

- Continue logging decisions in `DECISIONS.md` (this file) as the version-controlled mirror of ChatGPT Project state
- AI agents: when in doubt, check this file before asking the human for context

---

## Decision 002: Maintain AI運営OS用/docs/ Separate from Code-Level Docs

- **Date**: 2026-05-16
- **Status**: ACTIVE
- **Decided by**: Human founder + Claude Code

### Context

The repository has two distinct audiences:
1. **Developers / PyPI users** — need API reference, quickstart, and security guarantees (`README.md`, `src/`, `tests/`)
2. **AI operating agents** — need operational context, business logic, experiment history, and behavior protocols

Mixing these would cause AI agents to pollute developer-facing docs with operational noise, or developers to be confused by AI-internal protocol documents.

### Decision

All AI-native operational documents live exclusively under **`AI運営OS用/docs/`**.
No operational docs are written to the repository root or `docs/` (if that ever exists).
Existing code files (`src/`, `tests/`, `pyproject.toml`, `README.md`) are never modified by documentation tasks.

### Why

- Clean separation of concerns: a PyPI user reads `README.md`; an AI agent reads `AI運営OS用/docs/AI_INSTRUCTIONS.md`
- Prevents accidental overwrite of developer-facing content during AI documentation runs
- Makes it easy to audit: anything under `AI運営OS用/` is AI-operational, everything else is product

### Tradeoffs

| Pro | Con |
|-----|-----|
| Zero risk of polluting developer docs | Two places to maintain (ChatGPT Project + this dir) |
| AI agents have a stable, predictable read path | Japanese directory name may confuse non-Japanese tools |
| Survives AI context resets — always on disk | Requires AI agents to know to look here |

### Next Action

- All future AI-operational docs go under `AI運営OS用/docs/`
- If a `docs/` directory for developer documentation is ever created, it must remain entirely separate

---

## Decision 003: Protect `main` Branch with CI Before Any PR Merges

- **Date**: 2026-05-17
- **Status**: ACTIVE
- **Decided by**: Human founder + Claude Code

### Context

As AI agents begin autonomously opening PRs and making changes, there is a risk that:
- A test regression slips in undetected
- Crawler coverage drops below 100% (the 4-layer SSRF defense is security-critical)
- Python 3.14 compatibility breaks silently

A manual review process is insufficient at the pace of AI-assisted development.

### Decision

**`.github/workflows/ci.yml`** enforces two gates on every push and PR to `main`:
1. All 153 pytest tests must pass
2. `src/core/agentpass_crawler.py` must maintain 100% branch coverage

No PR may merge to `main` without these gates passing.

### Why

- Crawler is the security perimeter (SSRF, stream limit, validation) — 100% coverage is non-negotiable
- 153 tests represent the full defensive contract established in Weeks 1–4; regressions here = security regression
- Python 3.14 pre-release (`allow-prereleases: true`) must be tested explicitly because stdlib behavior can change (e.g., `ipaddress.is_private` for RFC 5737 addresses changed in 3.14)

### Tradeoffs

| Pro | Con |
|-----|-----|
| Catches regressions before merge | CI adds ~30–60s to PR feedback loop |
| Crawler 100% gate prevents security coverage drift | Python 3.14 pre-release may occasionally break on upstream changes |
| Artifact upload gives coverage history | No Slack/email alert on failure (yet) |

### Next Action

- Configure GitHub branch protection rules to require CI to pass before merge (currently not enforced at the GitHub UI level — only CI exists)
- Consider adding a `--fail-under=90` overall coverage gate once total coverage is measured

---

## Decision 004: 153-Test Floor — Never Reduce Without Explicit Review

- **Date**: 2026-05-16
- **Status**: ACTIVE
- **Decided by**: Human founder + Claude Code

### Context

During Week 1–4 implementation, tests were added and occasionally refactored. One refactoring reduced test count from 179 → 147 (removing old integration-style tests in favor of focused unit tests). This caused confusion: is a reduction "evolution" or regression?

The final count after coverage hardening was **153 tests**. Each test maps to a specific defensive boundary or behavioral contract.

### Decision

**153 is the floor, not a target.** Tests may be added freely. Tests may only be removed if:
1. The underlying code they test has been deleted, AND
2. A human explicitly approves the removal in a PR description

AI agents must never delete tests autonomously to make a test suite "cleaner."

### Why

- Tests encode security guarantees (SSRF, replay attack, budget limits) — losing a test = losing a guarantee
- The 179→147 reduction caused a coverage gap (89%) that required 6 tests to restore
- "Fewer tests = cleaner" is a dangerous heuristic in security-critical code

### Tradeoffs

| Pro | Con |
|-----|-----|
| Security contracts are always verified | Test suite grows over time |
| AI agents cannot silently weaken defenses | May include some redundant coverage |
| CI enforces the floor automatically | Requires discipline when refactoring |

### Next Action

- CI already enforces this implicitly (153 tests must pass)
- When new features are added, add tests first (test-driven for security-critical paths)
- Document test intent in `TESTING_POLICY.md` when non-obvious

---

## Decision 005: Sandbox Experimentation Is the Center of Phase 2

- **Date**: 2026-05-17
- **Status**: ACTIVE
- **Decided by**: Human founder

### Context

Wave 1 (ecosystem/packaging) is functionally complete:
- Core library implemented and tested (153 tests, 100% crawler coverage)
- PyPI packaging ready (`v1.0.0-beta1`)
- GitHub Actions CI active
- AI Operations OS docs established

The business model ("goldfish-shovel") depends on early merchant and agent adoption. The next risk to de-risk is: **will real AI agents actually use AgentPass in practice?**

### Decision

**Wave 2 focus = Sandbox experimentation**, not feature expansion. Specifically:
- Build a minimal merchant simulator that serves `agentpass.json` locally
- Build a minimal agent client that calls `AgentPassCrawler` + `issue_token()` end-to-end
- Run experiments with real AI agents (ChatGPT function calling, Claude tool_use, Gemini function calling) against the sandbox
- Log results in `EXPERIMENT_LOG.md` as EXP-004 and beyond

No new core features (new JWT claims, new middleware, new DB) until sandbox experiments validate the current feature set.

### Why

- Building more features before validating usage = waste
- Sandbox experiments are low-cost, reversible, and yield direct signal
- Experiment results will drive the Wave 2 feature backlog, not assumptions
- AI agents can run sandbox experiments autonomously, accelerating the feedback loop

### Tradeoffs

| Pro | Con |
|-----|-----|
| Fast feedback on real-world fit | Sandbox ≠ production; results may not generalize |
| Low cost — no infra needed for local sandbox | Requires experiment discipline (log everything in EXP log) |
| AI agents can participate directly | May reveal fundamental design flaws that require Wave 1 rework |
| Validates before PyPI publish | Delays PyPI publish and public announcement |

### Next Action

1. Design sandbox merchant server (`examples/sandbox_merchant.py`)
2. Design sandbox agent client (`examples/sandbox_agent.py`)
3. Define EXP-004 hypothesis: "A Claude tool_use agent can complete a full AgentPass payment handshake in under 3 round trips"
4. Run experiment, log in `EXPERIMENT_LOG.md`
5. Decide whether to publish to PyPI based on EXP-004/005 results

---

## Template for Future Decisions

```markdown
## Decision XXX: Title

- **Date**: YYYY-MM-DD
- **Status**: ACTIVE | SUPERSEDED | UNDER_REVIEW
- **Decided by**: Human founder | AI agent | Both
- **Supersedes**: Decision NNN (if applicable)

### Context

What situation or problem prompted this decision?

### Decision

What was decided, stated precisely.

### Why

The primary reason(s). Link to evidence or experiments where possible.

### Tradeoffs

| Pro | Con |
|-----|-----|
| ... | ... |

### Next Action

Concrete next steps that follow from this decision.
```

---

_Maintained by: Human founder + AI operating agents_
_AI agents: treat ACTIVE decisions as hard constraints; flag UNDER_REVIEW decisions before acting on them_
