# CLAUDE CODE WORKFLOW

> Operating rules for Claude Code as an AgentPass development agent.
> This document defines what Claude Code may do autonomously, what requires human approval,
> and how to structure instructions for safe, reproducible AI-assisted development.
>
> Intended readers: Human founder, Claude Code sessions, other AI operating agents.
> OSS-ready: These rules are safe to publish alongside the codebase.

---

## 1. Claude Code's Role

Claude Code operates as a **development partner**, not an autonomous deployer.
Its role is bounded to the following areas:

| Role | Description |
|------|-------------|
| **Implementation assistance** | Write or modify Python code under `src/` per explicit instruction |
| **Test addition** | Add new tests to `tests/`; never remove or weaken existing tests |
| **Refactoring** | Restructure code without changing behavior; tests must stay green |
| **Docs updates** | Write or update Markdown files under `AI運営OS用/docs/` |
| **Sandbox experiment assistance** | Build `examples/` scripts; log results in `EXPERIMENT_LOG.md` |

Claude Code is **not** a deployment agent and **not** a secrets manager.
All production-facing actions require explicit human approval at the point of execution.

---

## 2. Work Claude Code May Do Autonomously

Claude Code may perform the following without asking for confirmation each time:

- Create a new git branch (`git checkout -b feat/...`)
- Run `pytest` and report results
- Run `coverage report` and interpret output
- Add or edit Markdown files (docs only; no overwriting existing files without instruction)
- Add files under `examples/` (sandbox scripts, usage demos)
- Make small, scoped implementation fixes where the scope is clearly defined
- Update `EXPERIMENT_LOG.md` with experiment results
- Read any file in the repository
- Run `git status`, `git diff`, `git log`
- Run `git add` and `git commit` (with an appropriate commit message)

**Autonomy boundary**: Claude Code may commit but must pause before push.
Commit → human confirms → push.

---

## 3. Work Claude Code Must NOT Do

The following are hard prohibitions. Claude Code must refuse or pause and ask, even if instructed:

| Prohibited Action | Reason |
|-------------------|--------|
| Enter or store production secrets, API keys, or credentials | Secret leakage risk; irreversible |
| Push directly to `main` | `main` is the stable branch; CI gate and human review are required |
| Create or modify GitHub Actions secrets or repository settings | Affects all CI runs; requires human judgment |
| Change GitHub branch protection rules | Could silently remove safety gates |
| Run `twine upload` or any PyPI publish command | Irreversible; version cannot be unpublished |
| Delete or weaken any of the 153 existing tests | Tests encode security guarantees (see DECISIONS.md Decision 004) |
| Run `git reset --hard` or `git push --force` without explicit human instruction | Destructive; can destroy uncommitted work or rewrite shared history |
| Modify `.env`, `secrets.*`, or any credential file | Secrets must never be touched by automated agents |

If Claude Code encounters a task that would require any of the above,
it must **stop, explain why it is pausing, and ask the human for a decision**.

---

## 4. Commands That Require Explicit Human Confirmation

Before running any of the following, Claude Code must display the exact command and wait for approval:

```
# Version control — destructive or shared-state
git push [any flags]
git push --force
git reset --hard
git rebase [anything on main]
git branch -D

# File deletion
rm / rmdir / shutil.rmtree / os.remove (on any non-temp file)

# Deployment and publishing
vercel deploy
twine upload
pip publish
docker push

# Secrets and environment
export <SECRET>=...
vercel env add / pull / rm
gh secret set
direnv allow (on a modified .envrc)

# Permission changes
chmod / chown
gh repo edit
```

**How to request confirmation**: Claude Code must output:

```
ACTION REQUIRED — Human approval needed before proceeding.

Command: <exact command>
Effect: <what this will do>
Reversible: Yes / No / Partially
Proceed? (y/n)
```

---

## 5. Standard Work Flow

Every non-trivial task follows this sequence. Claude Code must not skip steps.

```
1. CONFIRM SCOPE
   └─ Read the instruction. Identify: what changes, what must NOT change.
   └─ Check DECISIONS.md for standing constraints that apply.

2. CREATE BRANCH
   └─ git checkout -b <type>/<short-description>
   └─ Types: feat / fix / test / docs / refactor / ci / experiment

3. MAKE CHANGES
   └─ Edit only the files in scope.
   └─ If a new file is needed, confirm path is correct before writing.

4. RUN TESTS
   └─ .venv/bin/pytest --tb=short -q
   └─ Must show: N passed (N ≥ 153), 0 failed, 0 errors.

5. CHECK COVERAGE (if crawler or core was touched)
   └─ .venv/bin/coverage report --include="src/core/agentpass_crawler.py" --fail-under=100

6. REVIEW DIFF
   └─ git diff HEAD
   └─ Confirm: no unintended files changed, no secrets in diff.

7. UPDATE OPERATIONAL DOCS (if applicable)
   └─ CHANGELOG.md — if a meaningful change was made
   └─ DECISIONS.md — if a new architectural decision was reached
   └─ EXPERIMENT_LOG.md — if an experiment was run

8. COMMIT
   └─ git add <specific files only, never -A blindly>
   └─ git commit -m "<type>: <description>"
   └─ Co-Authored-By line is optional but encouraged.

9. PAUSE FOR PUSH
   └─ Output push command for human to approve.
   └─ Do not push until human confirms.

10. OUTPUT REPORT
    └─ See Section 7 for required report format.
```

---

## 6. `main` Branch Operating Rules

| Rule | Detail |
|------|--------|
| `main` is the stable branch | Only production-ready code lives here |
| Direct push to `main` is prohibited | All changes arrive via PR |
| CI must be green before merge | `.github/workflows/ci.yml` must pass: 153 tests + 100% crawler coverage |
| 153-test floor is enforced | CI fails if any test is removed or if total count drops below 153 |
| Crawler coverage must be 100% | `src/core/agentpass_crawler.py` is the security perimeter |
| Human reviews all PRs before merge | Even AI-authored PRs require human merge approval |

Claude Code should create PRs with `gh pr create`, never merge them.

---

## 7. Standard Instruction Template (Human → Claude Code)

When giving Claude Code a task, use this format for clear, safe, reproducible results.
Copy, fill in, and send.

```markdown
## Goal
<What should exist or work differently after this task is complete?>

## Current Context
- Branch: <current branch or "create new branch feat/...">
- Relevant files: <list key files Claude Code should read first>
- Recent changes: <any recent commits or decisions that affect this task>

## Scope
<Exactly which files may be created or modified?>
<What behavior must be added / fixed / changed?>

## Do Not Change
- [ ] Existing tests in `tests/` (153 tests must remain intact)
- [ ] `src/core/agentpass_crawler.py` coverage must stay 100%
- [ ] <any other specific files or behaviors to protect>

## Required Checks
- [ ] `.venv/bin/pytest --tb=short -q` → 153+ passed, 0 failed
- [ ] `git diff HEAD` reviewed before commit
- [ ] <any additional checks specific to this task>

## Output Report
After completing, output:
- Files created or modified (with line counts)
- Test result (N passed)
- Coverage result (if applicable)
- Commit hash
- Next recommended action
```

---

## 8. Task Templates

Use these pre-filled templates for the three most common task types.

---

### Template A — Docs Update

```markdown
## Goal
Update / add documentation to AI運営OS用/docs/ to reflect <change or new decision>.

## Current Context
- Branch: create new branch docs/<short-name>
- Relevant files: AI運営OS用/docs/CHANGELOG.md, AI運営OS用/docs/DECISIONS.md
- Recent changes: <describe what just happened that needs to be documented>

## Scope
- May create or edit: AI運営OS用/docs/*.md only
- May NOT touch: src/, tests/, pyproject.toml, README.md, .github/

## Do Not Change
- [ ] All existing code files
- [ ] All existing tests (153 floor)
- [ ] Existing doc content (only append / add new sections)

## Required Checks
- [ ] `.venv/bin/pytest --tb=no -q` → 153 passed (sanity check; no code was changed)
- [ ] `git diff HEAD` shows only .md file changes

## Output Report
- Files created/modified
- Summary of content added (2–3 sentences)
- Commit hash
- Suggested git push command (human will approve)
```

---

### Template B — Implementation Fix or Feature

```markdown
## Goal
<Describe the behavior to fix or feature to add, in one sentence.>

## Current Context
- Branch: create new branch <feat|fix>/<short-name>
- Relevant files: <list specific src/ files to read first>
- Test file to update: <tests/test_*.py>
- Recent changes: <any prior work Claude Code should be aware of>

## Scope
- May create or modify: src/<module>.py, tests/test_<module>.py
- Must NOT touch: other src/ files, other test files, CI config

## Do Not Change
- [ ] 153 existing tests — do not delete, do not rename, do not weaken assertions
- [ ] `src/core/agentpass_crawler.py` coverage (must remain 100% if touched)
- [ ] Public API surface of `src/agentpass/__init__.py` unless explicitly instructed

## Required Checks
- [ ] `.venv/bin/pytest --tb=short -q` → N passed (N ≥ 153), 0 failed
- [ ] `.venv/bin/coverage report --include="src/core/agentpass_crawler.py" --fail-under=100` (if crawler touched)
- [ ] `git diff HEAD` — no unintended changes, no secrets

## Output Report
- Files modified (with before/after line counts)
- New tests added (list test names)
- pytest result: N passed
- Coverage result (if applicable)
- Commit hash
- Suggested next step (PR? further testing?)
```

---

### Template C — Sandbox Experiment

```markdown
## Goal
Run experiment EXP-<NNN>: <hypothesis in one sentence>.

## Current Context
- Branch: create new branch experiment/exp-<NNN>-<short-name>
- Hypothesis: <what we expect to observe>
- Success criterion: <what result would confirm the hypothesis>
- Failure criterion: <what result would refute it>
- Relevant files: examples/, EXPERIMENT_LOG.md

## Scope
- May create: examples/exp_<NNN>_*.py (sandbox scripts only)
- May update: AI運営OS用/docs/EXPERIMENT_LOG.md (append new EXP entry only)
- Must NOT touch: src/, tests/, pyproject.toml

## Do Not Change
- [ ] 153 existing tests
- [ ] Any existing EXPERIMENT_LOG entries (append only)
- [ ] Production configuration

## Required Checks
- [ ] `.venv/bin/pytest --tb=no -q` → 153 passed (sanity; no core code changed)
- [ ] Experiment script runs without unhandled exceptions
- [ ] EXPERIMENT_LOG.md updated with: Date / Hypothesis / Method / Result / Conclusion

## Output Report
- Experiment script created: examples/<filename>.py
- Result: CONFIRMED / REFUTED / INCONCLUSIVE
- Key observations (2–4 bullet points)
- EXPERIMENT_LOG.md updated: Yes/No
- Commit hash
- Recommended follow-up (next experiment? design change? proceed to EXP-<NNN+1>?)
```

---

## Appendix: Quick Reference

```
# Always safe to run
.venv/bin/pytest --tb=short -q
.venv/bin/coverage report --include="src/core/agentpass_crawler.py"
git status / git diff / git log --oneline

# Requires human confirmation before execution
git push
git reset --hard
rm <any file>
twine upload
vercel deploy
gh secret set
```

```
# Branch naming convention
feat/<name>       — new feature
fix/<name>        — bug fix
test/<name>       — test addition or coverage
docs/<name>       — documentation only
refactor/<name>   — restructure without behavior change
ci/<name>         — CI/CD changes
experiment/<name> — sandbox experiment
```

---

_This document is part of the AgentPass AI Operations OS._
_For architectural decisions, see DECISIONS.md._
_For experiment history, see EXPERIMENT_LOG.md._
_For testing rules, see TESTING_POLICY.md._
