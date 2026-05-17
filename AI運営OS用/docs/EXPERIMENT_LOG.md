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
**Status:** ✅ Completed
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

- [x] `sandbox_agent.py` が token を `issue_token()` で取得できる
- [x] `sandbox_merchant.py` が `verify_token()` でトークンを検証できる
- [x] 1回目のアクセスが 200 OK で返る
- [x] 2回目の同一 token 利用が 401 で拒否される（`AnomalyDetector` 経由）
- [x] `audit_exp004.jsonl` に両 attempt の結果が記録される
- [x] 実行後 `.venv/bin/pytest --tb=no -q` → 153 passed（既存テスト無破壊）

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

### Setup

```
examples/sandbox_merchant.py  — stdlib http.server ベースの最小merchantサーバー
examples/sandbox_agent.py     — httpx + issue_token による agent クライアント
examples/sandbox_keys.json    — 起動時生成・gitignore済み（Ed25519 鍵ペア）
examples/audit_exp004.jsonl   — 実行時生成・gitignore済み（JSONL 監査ログ）
```

実行手順:
```bash
# terminal 1
python examples/sandbox_merchant.py

# terminal 2
python examples/sandbox_agent.py
```

### Result

```
[Step 1] Metadata fetch      → 200 OK  merchant_id=sandbox-merchant-001
[Step 2] Keypair loaded      → sandbox_keys.json, keys match merchant's public_key=True
[Step 3] Token issued        → jti=695652e9-... valid_until=02:10:17Z amount=0.001 JPY
[Step 4] Attempt 1 (fresh)   → 200 Access granted  amount_charged=0.001 JPY  ✓
[Step 5] Attempt 2 (replay)  → 401 Replay attack detected  ✓
exit code: 0 (all criteria met)
```

audit_exp004.jsonl (2 lines):
```jsonl
{"attempt": 1, "status": "success", "http_status": 200, "jti": "695652e9-...", "agent_id": "sandbox-agent-001", "amount_jpy": 0.001, "ts": "2026-05-17T02:09:17Z"}
{"attempt": 2, "status": "replay_rejected", "http_status": 401, "jti": "695652e9-...", "ts": "2026-05-17T02:09:17Z"}
```

pytest after experiment: **153 passed** (no regressions)

### Problems

1. **AgentPassCrawler は localhost を SSRF で拒否する**
   - `sandbox_agent.py` で `AgentPassCrawler` を使おうとすると、127.0.0.1 が loopback と判定されてブロックされる
   - 対策: `httpx.get()` で直接 metadata を取得し、`MerchantMetadata.model_validate()` でパース（SSRF チェックをバイパス）
   - これは設計通りの動作 — 本番では SSRF 保護が必要

2. **`core/__init__.py` のトランジティブインポートが sys.path に依存**
   - `from core.anomaly_detector import AnomalyDetector` が `core/__init__.py` を実行し、`authorization_middleware.py` の `from src.core.xxx import` が走る
   - `src` に加えて プロジェクトルート (`.`) も sys.path に追加する必要があった
   - pytest の `pythonpath = ["src", "."]` と同じ設定で解決

3. **TokenRequest.destination_url が `https://` 必須**
   - sandbox は HTTP でサーブするが、JWT `aud` クレームに使う URL は `https://` が必要
   - `MERCHANT_AUD = "https://sandbox.agentpass.local/api/data"` として宣言し、merchant / agent で共有

### Learnings

- **仮説は確認された**: Ed25519 JWT + AnomalyDetector だけで AIエージェントの安全な一回限りのAPI購入フローを実現できる
- **AgentPassCrawler の SSRF ガードは sandbox と互換性がない**: これは正しい設計（本番では localhost へのアクセスを防ぐべき）。sandbox 用の `AgentPassCrawler(ssrf_bypass=True)` を追加するより、「sandbox は httpx 直アクセス」と文書化する方がシンプル
- **同一鍵ペアを merchant/agent で共有するのは sandbox の簡略化**: 本番では agent が独自の秘密鍵を持ち、merchant は agent のレジストリから公開鍵を取得する必要がある（Wave 2 課題）
- **`core/__init__.py` のインポートが重い**: `authorization_middleware.py` など、スクリプト実行には不要なモジュールまで読み込まれる。将来的に `core/__init__.py` を遅延インポートにするか、スクリプト向け軽量エントリポイントを作ることを検討

### Next Action

- [x] `examples/sandbox_merchant.py` 作成（完了）
- [x] `examples/sandbox_agent.py` 作成（完了）
- [x] 実験実行 → 全成功基準クリア
- [ ] EXP-005: マルチエージェント競合テスト（複数エージェントが同一 JTI を同時送信した場合の AnomalyDetector 挙動）の設計
- [ ] Wave 2 課題: agent 独自鍵ペアと merchant 側の公開鍵レジストリ設計
- [ ] `core/__init__.py` の遅延インポート検討（軽量スクリプト実行のため）

---

## 次の実験候補

| ID | タイトル | 仮説 | 優先度 | 状態 |
|---|---|---|---|---|
| EXP-004 | Minimal AgentPass Sandbox Purchase Flow | 使い捨てトークンだけでAIエージェントの安全なAPI購入を再現できる | 最高 | ✅ Completed |
| EXP-005 | PyPI 実公開テスト | `python -m build && twine upload` が問題なく通る | 高 | 未着手 |
| EXP-006 | マルチエージェント競合テスト | 複数エージェントが同一JTIを同時送信した場合のAnomalyDetector挙動 | 中 | 未着手 |
| EXP-007 | CircuitBreaker スレッド安全性 | 100スレッド同時発行でも原子性が保たれる | 中 | 未着手 |
| EXP-008 | Wave 2 信用スコア API PoC | `CreditScorer` を REST API として公開できるか | 低 | 未着手 |
