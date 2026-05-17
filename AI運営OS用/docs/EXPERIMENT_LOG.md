# Experiment Log — AgentPass Sandbox

> Sandbox 実験・PoC・AI 行動ログを資産化する。  
> 仮説 → 結果 → 学習 のサイクルを記録し、次の行動に繋げる。

---

## How to Use This Log

新しい実験を開始したら、以下テンプレートをコピーして追加する。  
実験 ID は `EXP-{3桁連番}` 形式。

---

## Experiment Template

```markdown
## EXP-XXX — {実験タイトル}

**Date:** YYYY-MM-DD  
**Status:** 🔄 In Progress | ✅ Completed | ❌ Abandoned  
**Owner:** {担当者 or AI エージェント名}

### Goal
何を確認・達成しようとしているか。1〜3文で。

### Hypothesis
「〇〇すれば△△になる」という形式で。

### Setup
実験環境・使用したコード・設定。

### Result
実際に何が起きたか。数値・ログ・エラーメッセージを含める。

### Problems
発生した問題・想定外の挙動。

### Learnings
次のセッションに持ち越せる知見。

### Next Action
- [ ] 次にやること1
- [ ] 次にやること2
```

---

## EXP-001 — Python 3.14 における ipaddress.is_private の挙動確認

**Date:** 2026-05-17  
**Status:** ✅ Completed  
**Owner:** Claude Code (claude-sonnet-4-6)

### Goal
SSRF テストで使用していた `203.0.113.1`（RFC 5737 TEST-NET-3）が Python 3.14 でどう扱われるかを確認する。

### Hypothesis
「RFC 5737 ドキュメント用アドレスはパブリック IP として扱われる」

### Setup
```python
import ipaddress
print(ipaddress.ip_address("203.0.113.1").is_private)
```

### Result
```
True
```
Python 3.14 では RFC 5737 TEST-NET-3 が `is_private=True` に分類される。

### Problems
SSRF テストのモック IP を `203.0.113.1` にしていたため、テストが失敗した（SSRF チェックで意図せず拒否された）。

### Learnings
- Python 3.14 では `ipaddress.is_private` の定義が RFC 6890 ベースに拡大された
- RFC 5737 (TEST-NET-1/2/3), RFC 3849 (IPv6 ドキュメント) はすべて `is_private=True`
- SSRF テストのモック「公開 IP」は `8.8.8.8`（Google DNS）または `1.1.1.1`（Cloudflare）を使うこと
- テストは実行環境の Python バージョンに依存する箇所に注意が必要

### Next Action
- [x] 全 SSRF テストのモック IP を `8.8.8.8` に変更（完了）
- [x] `TESTING_POLICY.md` に Python 3.14 の注意点を明記（完了）

---

## EXP-002 — agentpass_crawler.py カバレッジ 89% → 100% の穴埋め

**Date:** 2026-05-17  
**Status:** ✅ Completed  
**Owner:** Claude Code (claude-sonnet-4-6)

### Goal
`test_agentpass_crawler.py`（旧26件 → 新14件）への移行で失われたカバレッジを特定・補完する。

### Hypothesis
「新14件では旧26件からカバーが漏れた分岐が存在する」

### Setup
```bash
.venv/bin/pytest tests/test_agentpass_crawler.py tests/e2e/ \
  --cov=src --cov-report=term-missing
```

### Result
初期カバレッジ: **89%**。未カバー行: 130, 144-145, 173, 182-183, 186, 197-198

| 行 | 分岐 |
|---|---|
| 130 | DNS が空 IP リストを返した場合 |
| 144-145 | IP 文字列がパース不能な場合 |
| 173 | ネットワークタイムアウト・接続エラー |
| 182-183 | 不正 JSON バイト列 |
| 186 | JSON が配列（オブジェクトでない） |
| 197-198 | Pydantic スキーマ検証失敗 |

### Problems
6つの防衛分岐（= 6つの攻撃ベクトル）がテストされていなかった。  
旧テストを削除した際、これらの分岐のカバーが失われていた。

### Learnings
- テスト件数削減は「退化」ではなく「進化」の可能性があるが、**カバレッジ実測で確認必須**
- セキュリティ関連コードのリファクタリング後は必ずカバレッジ100%を確認する
- `respx.mock(side_effect=httpx.ConnectError(...))` でネットワークエラーをシミュレートできる

### Next Action
- [x] 6件のテストを追加（完了）
- [x] カバレッジ 100% 達成（完了）
- [x] `TESTING_POLICY.md` にカバレッジ要件を明記（完了）

---

## EXP-003 — PyPI src-layout パッケージング設計

**Date:** 2026-05-17  
**Status:** ✅ Completed  
**Owner:** Claude Code (claude-sonnet-4-6)

### Goal
既存153件のテスト（`from src.core.xxx` パターン）を壊さずに、`from agentpass import AuthorizationMiddleware` を実現する。

### Hypothesis
「`pythonpath = ["src", "."]` を pytest に追加することで、両方のインポートパスが共存できる」

### Setup
- `pyproject.toml`: `pythonpath = ["src", "."]` 追加、`package-dir = {"" = "src"}` 追加
- `src/agentpass/__init__.py` 新設: `from core.xxx import ...` パターン

### Result
- `from src.core.xxx import` → ✅（`.` 経由で `src` パッケージにアクセス）
- `from agentpass import ...` → ✅（`src` 経由で `agentpass` パッケージにアクセス）
- 153件全テスト → ✅ パス

### Problems
- `src/core/`, `src/identity/` が `package-dir = {"" = "src"}` によりインストール時に `core`, `identity` としてトップレベルに配備される（汎用名）
- Wave 2 以降で `agentpass.core.*` に移行する正式なリネームが必要

### Learnings
- src-layout で `package-dir = {"" = "src"}` を使うと、`src/` 内の全ディレクトリがトップレベルパッケージになる
- `pythonpath = ["src", "."]` の組み合わせで開発中・インストール後の両方をカバーできる
- `core` という汎用名はPyPI 上で名前衝突リスクがある（将来の懸念）

### Next Action
- [x] `src/agentpass/__init__.py` の22シンボル公開（完了）
- [ ] Wave 2 で `agentpass.core.*` への正式移行を検討
- [ ] `pip install agentpass` からのエンドツーエンド動作確認

---

## EXP-004 — Minimal AgentPass Sandbox Purchase Flow

**Date:** 2026-05-17
**Status:** 📐 Designing
**Owner:** Claude Code (claude-sonnet-4-6) + Human founder

### Goal

AI Agent → token issue → merchant access → data response → audit log の最小フローを、
外部依存ゼロのサンドボックスで検証する。
「AIエージェントの安全なAPI購入」が既存コアだけで実現可能かを確認する最初のE2E実験。

### Hypothesis

> 使い捨てトークン（Ed25519 JWT）と merchant 検証だけで、
> AIエージェントの安全なAPI購入フローを再現できる。
> かつ同一トークンの2回目利用は AnomalyDetector が確実に拒否する。

### Already Implemented (実装済み — src/ に存在)

| コンポーネント | 場所 | 状態 |
|---|---|---|
| `issue_token()` | `src/core/token_issuer.py` | ✅ 実装済み・テスト済み |
| `verify_token()` | `src/core/token_verifier.py` | ✅ 実装済み・テスト済み |
| `generate_keypair()` | `src/core/token_issuer.py` | ✅ 実装済み |
| `AnomalyDetector.is_replay_attack()` | `src/core/anomaly_detector.py` | ✅ 実装済み・テスト済み |
| `AgentPassCrawler.fetch_merchant_metadata()` | `src/core/agentpass_crawler.py` | ✅ 実装済み・100%カバレッジ |

### Not Yet Implemented (未実装 — sandbox に必要)

| コンポーネント | 場所（予定） | 内容 |
|---|---|---|
| `sandbox_merchant.py` | `examples/sandbox_merchant.py` | agentpass.json を返す最小HTTPサーバー / token 検証エンドポイント |
| `sandbox_agent.py` | `examples/sandbox_agent.py` | `AgentPassCrawler` + `issue_token` + HTTP呼び出し + audit log |
| audit log 出力 | `examples/sandbox_agent.py` 内 | JSONL 形式で `examples/audit_exp004.jsonl` に保存 |

### Scope

- `examples/sandbox_merchant.py` の新規作成
- `examples/sandbox_agent.py` の新規作成
- `AI運営OS用/docs/EXPERIMENT_LOG.md` の更新（本エントリの Result 欄）

### Out of Scope

- 実決済・外部API接続・KYC・本番ウォレット
- `src/` 以下の既存コードへの変更
- `tests/` 以下への変更（153テスト保護）
- PyPI 公開

### Experiment Flow (設計)

```
[sandbox_agent.py]
  1. AgentPassCrawler.fetch_merchant_metadata("localhost")
     └─ Returns: MerchantMetadata (public_key, merchant_id, pricing)

  2. issue_token(TokenRequest(
       agent_id = derive_agent_id(agent_private_key),
       merchant_id = metadata.merchant_id,
       amount = 0.001,
       currency = "JPY",
       destination = "http://localhost:8080/api/data",
     ))
     └─ Returns: IssuedToken (JWT string, jti, exp)

  3. GET http://localhost:8080/api/data
     Header: Authorization: Bearer <token>
     └─ Merchant verifies: verify_token() + AnomalyDetector.is_replay_attack()

  4. First request  → 200 OK, data returned
  5. Second request (same token) → 401 Rejected ("Replay attack detected")

  6. Write audit log → examples/audit_exp004.jsonl
     { "attempt": 1, "status": "success", "jti": "...", "ts": "..." }
     { "attempt": 2, "status": "rejected", "reason": "replay", "jti": "...", "ts": "..." }
```

### Success Criteria

- [ ] `sandbox_agent.py` が token を `issue_token()` で取得できる
- [ ] `sandbox_merchant.py` が `verify_token()` でトークンを検証できる
- [ ] 1回目のアクセスが 200 OK で返る
- [ ] 2回目の同一 token 利用が 401 で拒否される（`AnomalyDetector` 経由）
- [ ] `audit_exp004.jsonl` に両 attempt の結果が記録される
- [ ] 実行後 `.venv/bin/pytest --tb=no -q` → 153 passed（既存テスト無破壊）

### Risks

| リスク | 影響 | 対策 |
|---|---|---|
| 既存 token 仕様とのズレ | sandbox が core の期待と噛み合わない | `verify_token()` のシグネチャを先に読み確認する |
| replay 検知の抜け | 2回目が通ってしまう | `AnomalyDetector` の `_time_func` を固定してテスト |
| sandbox と core の責務混在 | `examples/` に core ロジックが漏れ込む | `examples/` は import のみ、実装は `src/` に書かない |
| 将来構想を入れすぎること | 実験が複雑化し結論が出ない | Scope を厳守。決済・KYC は Out of Scope |

### Required Checks (実装時)

```bash
# 実装後に必ず実行
.venv/bin/pytest --tb=short -q                        # 153 passed 必須
.venv/bin/python examples/sandbox_agent.py            # エラーなし必須
cat examples/audit_exp004.jsonl                       # 2行のログ確認
git diff HEAD                                         # src/ tests/ への変更がないこと
```

### Setup (実装時に記入)

_← 実装時に記入_

### Result (実装時に記入)

_← 実装時に記入_

### Problems (実装時に記入)

_← 実装時に記入_

### Learnings (実装時に記入)

_← 実装時に記入_

### Next Action

- [ ] `examples/sandbox_merchant.py` を作成（Template B で Claude Code に依頼）
- [ ] `examples/sandbox_agent.py` を作成（Template B で Claude Code に依頼）
- [ ] 実験を実行し、Result / Problems / Learnings を本エントリに追記
- [ ] 成功 → EXP-005（マルチエージェント競合）設計へ
- [ ] 失敗 → core の設計課題を特定し DECISIONS.md に記録

---

## 次の実験候補

| ID | タイトル | 仮説 | 優先度 | 状態 |
|---|---|---|---|---|
| EXP-004 | Minimal AgentPass Sandbox Purchase Flow | 使い捨てトークンだけでAIエージェントの安全なAPI購入を再現できる | 最高 | 📐 Designing |
| EXP-005 | PyPI 実公開テスト | `python -m build && twine upload` が問題なく通る | 高 | 未着手 |
| EXP-006 | マルチエージェント競合テスト | 複数エージェントが同一JTIを同時送信した場合のAnomalyDetector挙動 | 中 | 未着手 |
| EXP-007 | CircuitBreaker スレッド安全性 | 100スレッド同時発行でも原子性が保たれる | 中 | 未着手 |
| EXP-008 | Wave 2 信用スコア API PoC | `CreditScorer` を REST API として公開できるか | 低 | 未着手 |
