# AgentPass MASTER STATUS

Last Updated: 2026-05-17

---

# Current STATE

STATE ID: STATE-2026-05-17-BRANCH-PROTECTION-CONFIGURED

Current Phase:
OSS Release Preparation Phase

Current Priority:
TestPyPI 公開ワークフローの整備と外部インストール検証

Current Focus:
- `python -m build` で dist/ 生成
- `twine check dist/*` で配布物検証
- TestPyPI へのアップロード
- `pip install --index-url https://test.pypi.org/simple/ agentpass` 動作確認

Current Risks:
- `build` / `twine` が未インストール（要 pip install）
- `dist/` 未生成（ビルド未実行）
- branch protection は private repo のため CI 必須化は GitHub Team / public 移行後
- PyPI API トークンは環境変数 `TWINE_PASSWORD` への設定が必要

Next Required Action:
`pip install build twine` → `python -m build` → `twine check dist/*` →
`twine upload --repository testpypi dist/*` の順で実行し、
外部 install が通ることを確認する。

---

# Active Task

- Task ID: TASK-PYPI-PREP
- Title: TestPyPI 公開準備
- Owner Channel: 技術相談室
- Status: ACTIVE
- Started At: 2026-05-17
- Completion Criteria:
  以下のコマンドシーケンスが全て成功すること:

  ```
  pip install build twine
  python -m build
  twine check dist/*
  twine upload --repository testpypi dist/*
  pip install --index-url https://test.pypi.org/simple/ agentpass==1.0.0b1
  python -c "from agentpass import issue_token; print('ok')"
  ```

  ※ TestPyPI の API トークンは https://test.pypi.org/manage/account/token/ で取得
  ※ `TWINE_USERNAME=__token__` / `TWINE_PASSWORD=<token>` を環境変数にセット

---

# Task Queue

| Priority | Task ID | Task | Status | Owner Channel | Trigger | Notes |
|---|---|---|---|---|---|---|
| P2 | TASK-EXP008-REVOCATION-DESIGN | Token Revocation Layer設計 | PLANNED | Sandbox実験室 | TestPyPI公開完了後 | revocation boundary experiment |

---

# Done Tasks

| Task ID | Title | Completed At |
|---|---|---|
| TASK-EXP005A-STATUS-UPDATE | EXP-005a完了状態をMASTER_STATUSへ反映する | 2026-05-17 |
| TASK-EXP005B-DESIGN | EXP-005b Multi-agent JTI Collision設計 | 2026-05-17 |
| TASK-EXP006 | Replay / Collision Verification | 2026-05-17 |
| TASK-EXP005C-KEYPAIR-ISOLATION | Agent Keypair Isolation | 2026-05-17 |
| TASK-EXPERIMENT-LOG-RECONCILIATION | EXPERIMENT_LOG.md と README.md の整合性修正 | 2026-05-17 |
| TASK-README-REFRESH | README最新化（imports修正・test count 263） | 2026-05-17 |
| TASK-WAVE1-REALIGN | ROADMAP/Wave1整合性修正（sandbox実験反映） | 2026-05-17 |
| TASK-SECURITY-MD | SECURITY.md作成（4層防衛・開示プロセス・依存関係ポリシー） | 2026-05-17 |
| TASK-BRANCH-PROTECTION | branch protection ruleset 設定（private repo 制約を記録） | 2026-05-17 |

---

# Core Principles

- tests = protocol law
- experiment first
- replayable logs
- AI-readable structure
- implementation / hypothesis separation
- ACTIVE TASK is always singular

---

# Operational Rules

1. ACTIVE TASK は常に1つだけ
2. 新規提案はTASK QUEUEへ積む
3. ACTIVEを勝手に変更しない
4. 各チャットは最後に
   ACTIVE変更 or QUEUE追加
   を必ず明示する
5. 会話ログではなくSTATEを優先する

---

# Current Protected Assets

- 263 tests passing（Core 153 + Sandbox 110）
- 0 failed tests
- 100% coverage（core crawler）
- Sandbox Runtime operational
- Replay verification operational
- Multi-agent collision verification operational
- Agent keypair isolation verification operational
- External API structure operational（22 シンボル公開）
- GitHub Actions CI operational（Python 3.14）
- SECURITY.md present（プロジェクトルート）
- Branch protection ruleset configured

---

# Latest Completed Experiments

- EXP-004 Minimal Purchase Flow
- EXP-005a Budget Control + HTTP 402
- EXP-005b Multi-agent JTI Collision
- EXP-005c Agent Keypair Isolation
- EXP-006 Replay / Collision Verification

---

# Known Repository Notes

- Remote branch `experiment/exp-004-sandbox-merchant` remains on origin
  (inactive / merge-complete into main via PR #1)

- `git stash@{0}` contains old MASTER_STATUS snapshot from commit 4184dba
  (do not pop without verification)

- Branch protection ruleset configured locally,
  but CI-required-merge enforcement needs GitHub Team plan or public repository

- `dist/` directory does not exist yet（`python -m build` 未実行）

- `build` / `twine` は未インストール（TASK-PYPI-PREP 冒頭で `pip install build twine` が必要）

---

# Wave 1 Status

## Completed
- Core JWT/Auth infrastructure（22 シンボル・pyproject.toml v1.0.0-beta1）
- Sandbox runtime（EXP-004〜006 + EXP-005a/b/c 全5実験）
- Replay / collision / keypair isolation verification
- GitHub Actions CI（Python 3.14・pytest 263件）
- README synchronization（クイックスタート・テスト表）
- ROADMAP alignment（Wave1 sandbox 実験反映）
- SECURITY.md creation（脆弱性報告・4層防衛・ポリシー）
- Branch protection ruleset configuration

## Remaining
- TestPyPI 公開（`pip install build twine` → `python -m build` → `twine upload`）
- 外部インストール検証（`pip install agentpass==1.0.0b1` from TestPyPI）
- EXP-008 Token Revocation Layer（Wave 1 最終実験）

---

# Release Readiness

## Package Status
| 項目 | 状態 |
|------|------|
| package name | `agentpass` |
| version | `1.0.0-beta1` |
| src-layout | ✅ |
| pyproject.toml | ✅ |
| README.md | ✅ 最新化済み |
| SECURITY.md | ✅ プロジェクトルート |
| GitHub Actions CI | ✅ Python 3.14 |
| `python -m build` | ❌ 未実行（`build` 未インストール） |
| `twine check` | ❌ 未実行 |
| TestPyPI upload | ❌ 未実行 |
| 外部 install 確認 | ❌ 未検証 |

## Required Commands (順序厳守)

```bash
pip install build twine
python -m build
twine check dist/*
# TestPyPI API トークンを環境変数にセット後:
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ agentpass==1.0.0b1
python -c "from agentpass import issue_token; print('ok')"
```

---

# Security Status

## Supported Versions
- v1.0.0-beta1（current）

## Security Contact
- notenki.toclient@gmail.com

## Security Layers
- Ed25519 署名検証
- JWT 改ざん検知
- `aud` 宛先固定
- `jti` 使い捨て（replay 防御）
- SSRF 防御（DNS 解決 + private IP 即拒否）
- 1MB ストリーム制限

詳細: `SECURITY.md`（プロジェクトルート）

---

# Next STATE Candidate

STATE-2026-05-17-TESTPYPI-READY
