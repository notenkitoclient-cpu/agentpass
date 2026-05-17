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

## 次の実験候補

| ID | タイトル | 仮説 | 優先度 |
|---|---|---|---|
| EXP-004 | PyPI 実公開テスト | `python -m build && twine upload` が問題なく通る | 高 |
| EXP-005 | Sandbox 環境構築 | respx + FakeTime だけで本番同等フローを再現できる | 高 |
| EXP-006 | マルチエージェント競合テスト | 複数エージェントが同一JTIを同時送信した場合のAnomalyDetector挙動 | 中 |
| EXP-007 | CircuitBreaker スレッド安全性 | 100スレッド同時発行でも原子性が保たれる | 中 |
| EXP-008 | Wave 2 信用スコア API PoC | `CreditScorer` を REST API として公開できるか | 低 |
