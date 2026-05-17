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
- [x] マルチエージェント同一JTI競合テスト → EXP-005b で実施・検証済み
- [x] Wave 2 課題: agent 独自鍵ペアと merchant 側の公開鍵レジストリ → EXP-005c で実施・検証済み
- [ ] `core/__init__.py` の遅延インポート検討（軽量スクリプト実行のため）

---

## EXP-005a — Sandbox Budget Control（HTTP 402 Budget Gate）

**Date:** 2026-05-17
**Status:** ✅ Completed
**Owner:** Claude Code (claude-sonnet-4-6)

### Goal

Sandbox環境において、AIエージェントの1トランザクション支出を予算上限でゲートし、
超過時を HTTP 402 で拒否できるか検証する。
また、拒否イベントをappend-onlyなJSONL監査ログに記録し、
後から再検証（replay validation）できるかを確認する。

### Hypothesis

> `SandboxBudgetControl.check()` が冪等（状態変化なし）かつ監査可能であれば、
> 拒否イベントをappend-onlyログから再現・検証できる。

### Setup

新規パッケージ `src/agentpass/sandbox/` を作成:

```
errors.py         — SandboxBudgetExceededError (http_status=402, to_response())
budget_control.py — SandboxBudgetControl (check() は冪等)
audit_log.py      — AuditLog (append-only JSONL, make_budget_exceeded_record())
verifier.py       — SandboxVerifier (6ステップパイプライン)
```

6ステップパイプライン:
```
1. verify_token()     — 署名・有効期限・aud検証
2. claims検証        — verify_token() に内包
3. replay pre-check  — AnomalyDetector.is_replay_attack()
4. budget check      — SandboxBudgetControl.check()
5. 超過時            — audit_log.append() + SandboxBudgetExceededError送出
6. 成功時            — VerifiedClaimsを返す（成功ログは呼び出し元責務）
```

### Result

```
tests/sandbox/
  test_budget_exceeded_returns_402.py  — 20 tests (エラー属性・境界値・verifier統合)
  test_budget_rejection_audit_log.py   — 12 tests (append-only・必須フィールド・JSONL形式)
  test_budget_replay.py                — 12 tests (冪等性・verifier↔audit log往復)

既存 153 + 新規 44 = 197 passed / 0 failed
```

### Problems

なし。既存 core と責務を明確に分離できた。

### Learnings

- **sandbox は HTTP 402** (Payment Required) が意味的に正確。core の BudgetExceededError が使う 429（Too Many Requests）とは異なる語義
- **冪等設計が監査ログの価値を高める**: reject 時に状態変化しないため、同じ条件で何度でも再現検証できる
- **JSONL 形式 + REQUIRED_FIELDS で replay validation が自然に書ける**: テスト層でも「audit log を読んで再検証」というパターンが成立した

### Next Action

- [x] `src/agentpass/sandbox/` パッケージ作成（完了）
- [x] 44件テスト追加、197 passed（完了）
- [x] EXP-005b: JTI 衝突テストへ進む

---

## EXP-005b — JTI Collision / Thread-Safe Replay Guard

**Date:** 2026-05-17
**Status:** ✅ Completed
**Owner:** Claude Code (claude-sonnet-4-6)

### Goal

同一JTIを複数スレッドが同時送信したとき、承認が「ちょうど1件」に絞られることを
atomicに保証できるか検証する。
また、replay_detected と purchase_approved を監査ログに残し、
所有権の追跡を可能にする。

### Hypothesis

> `threading.Lock` を使った `check_and_register(jti) -> bool` を1操作にすれば、
> N スレッドが同一JTIを同時送信しても approved が厳密に1件になる。

### Setup

```python
# src/agentpass/sandbox/replay_guard.py
class ReplayGuard:
    def __init__(self):
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def check_and_register(self, jti: str) -> bool:
        with self._lock:
            if jti in self._seen:
                return False
            self._seen.add(jti)
            return True
```

SandboxVerifier に `replay_guard: ReplayGuard | None = None` パラメータを追加。
active 時は `is_replay_attack` を `check_and_register` で代替し、
`replay_detected` / `purchase_approved` 監査イベントを記録。

### Result

```
tests/sandbox/test_exp005b_jti_collision.py  — 16 tests

TestSequentialReplay   (6) — 逐次replay拒否・独立JTI両方承認
TestParallelCollision  (3) — 2スレッド=1承認・10スレッド=1承認・ReplayGuard単体並列
TestAuditLogEvents     (7) — purchase_approved/replay_detected 記録・token_id一致確認

既存 197 + 新規 16 = 213 passed / 0 failed
```

### Problems

**`from core.xxx import` vs `from src.core.xxx import` によるクラス同一性問題**

verifier.py が `from core.token_verifier import InvalidPayloadError` を使い、
テストが `from src.core.token_verifier import InvalidPayloadError` を使うと、
同一ファイルから生成された2つの異なるクラスオブジェクトになる。
`except InvalidPayloadError` がキャッチできず、スレッド内で例外が握りつぶされた。

修正: verifier.py のインポートを `from src.core.xxx import` に統一。

### Learnings

- **Python の sys.path 二重登録は module identity を分裂させる**: `pythonpath = ["src", "."]` により `core.X` と `src.core.X` が別クラスになる。except/isinstance が静かに失敗する
- **スレッドの未捕捉例外は pytest で PytestUnhandledThreadExceptionWarning になる**: 最初は `approved==1, rejected==0` というおかしな結果になり、これで問題を発見した
- **`threading.Lock` 内の check+register は1操作**: この単純な設計で N スレッド競合が完全に制御できた

### Next Action

- [x] ReplayGuard 実装（完了）
- [x] 16件テスト追加、213 passed（完了）
- [x] EXP-006: Replay Burst Freeze へ進む

---

## EXP-006 — Replay Burst Freeze（異常バーストによる一時停止）

**Date:** 2026-05-17
**Status:** ✅ Completed
**Owner:** Claude Code (claude-sonnet-4-6)

### Goal

短時間に replay_detected が連続発生したとき、スライディングウィンドウで異常バーストを検知し、
支出を一時 freeze できるか検証する。
SandboxVerifier と ReplayGuard の責務を増やさずに実現できるかを確認する。

### Hypothesis

> SandboxVerifier を変更せず外側に FreezeLayer でラップすれば、
> バースト検知と freeze 発動をポリシー層として分離できる。

### Setup

```
src/agentpass/sandbox/
  burst_freeze.py  — BurstFreezeDetector (sliding window + threading.Lock, injectable timestamp)
  freeze_layer.py  — FreezeLayer (SandboxVerifier をラップ; is_frozen()/record_replay() を呼ぶ)
  errors.py        — SpendingFrozenError (http_status=503) 追記
  audit_log.py     — make_spending_frozen_record() 追記
```

FreezeLayer のフロー:
```
1. is_frozen() → True  → spending_frozen 記録 + SpendingFrozenError(503)
2. inner.verify(token) → 委譲
3. InvalidPayloadError + "Replay attack detected" → record_replay()
   → 新規 freeze 発動なら spending_frozen 記録
4. 成功 → VerifiedClaims をそのまま返す
```

タイムスタンプは `now: float | None = None` で injectable → モックレスで時刻制御テストを実現。

### Result

```
tests/sandbox/test_exp006_burst_freeze.py  — 22 tests

TestBurstFreezeDetector (11) — 未到達・到達・window期限切れ・concurrent 1 trigger
TestFreezeLayer         (6)  — 正常通過・単発replay非freeze・バーストfreeze・HTTP503
TestAuditLogFreezeEvent (5)  — spending_frozen記録・burst_count・freeze後ゲート記録

既存 213 + 新規 22 = 235 passed / 0 failed
SandboxVerifier・ReplayGuard への変更: ゼロ
```

### Problems

なし。FreezeLayer の `_REPLAY_SIGNAL = "Replay attack detected"` による文字列マッチングは
sandbox 用途として許容範囲。本番なら専用例外クラスが望ましい。

### Learnings

- **ラッパーパターンで責務を無限に分離できる**: SandboxVerifier も ReplayGuard も触らずに freeze ポリシーを追加できた
- **タイムスタンプ injection でモックレス時刻テストが可能**: `time.monotonic()` のデフォルトと injectable `now` の両立が有効
- **freeze は「trigger 時」と「gate 時」の2箇所で記録が必要**: trigger=freeze を開始したイベント、gate=freeze 中にリクエストが来たイベント。両方が audit log にないと後から因果を追えない

### Next Action

- [x] BurstFreezeDetector / FreezeLayer 実装（完了）
- [x] 22件テスト追加、235 passed（完了）
- [x] EXP-005c: Agent Keypair Isolation へ進む

---

## EXP-005c — Agent Keypair Isolation（マルチエージェント鍵境界）

**Date:** 2026-05-17
**Status:** ✅ Completed
**Owner:** Claude Code (claude-sonnet-4-6)

### Goal

エージェントごとに署名鍵を分離し、multi-agent 環境での trust boundary を検証する。
「compromised な agent の鍵が他の agent に影響しないこと」と
「signer の identity が audit log で追跡可能なこと」を確認する。

### Hypothesis

> JWT `kid` ヘッダで key_id を渡し、AgentKeyRegistry で `key_id → (agent_id, pubkey, status)` を管理すれば、
> agent ごとの鍵分離・compromised 隔離・signer mismatch 拒否が実現できる。

### Setup

```
src/agentpass/sandbox/
  agent_key_registry.py — AgentKeyRegistry (key_id → agent_id + Ed25519PublicKey + status)
  signer.py             — SandboxSigner (agent別署名 + JWT kid ヘッダ)
  verifier.py           — optional key_registry パラメータ追加（最小拡張）
  errors.py             — 4エラー追記
  audit_log.py          — signer_verified / signer_rejected ファクトリ追記
```

検証フロー (SandboxVerifier + key_registry 有効時):
```
Step 0. jwt.get_unverified_header(token)["kid"] → key_id を取得
Step 0b. registry.resolve(key_id) → (owner_agent_id, public_key)
         CompromisedKeyError / UnknownKeyIdError → signer_rejected 記録 + raise
Step 1-2. verify_token(token, resolved_pubkey, merchant_url) — 署名・exp・aud
Step 2b. claims.agent_id != owner_agent_id → signer_rejected 記録 + SignerMismatchError(403)
Step 3-5. replay / budget (既存と同じ)
Step 6. signer_verified 記録 + VerifiedClaims 返却
```

追加エラー:
```
SignerMismatchError    403 SIGNER_MISMATCH
CompromisedKeyError   403 SIGNER_COMPROMISED
UnknownKeyIdError     401 UNKNOWN_KEY_ID
UnknownAgentIdError   401 UNKNOWN_AGENT_ID
```

### Result

```
tests/sandbox/test_exp005c_agent_keypair_isolation.py  — 28 tests

TestAgentKeyRegistry       (8) — 登録・解決・compromised・独立性確認
TestSandboxSigner          (6) — kidヘッダ・sub一致・正しい鍵で検証可・別鍵で検証不可
TestMultiAgentVerification (7) — agent-A鍵でA承認・B鍵でB承認・mismatch拒否・compromised隔離
TestAuditLogSignerEvents   (7) — signer_verified記録・signer_rejected記録・フィールド確認

既存 235 + 新規 28 = 263 passed / 0 failed
```

### Problems

なし。JWT `kid` ヘッダの追加は PyJWT の `headers={"kid": key_id}` と
`jwt.get_unverified_header()` だけで完結した。

### Learnings

- **JWT `kid` は標準ヘッダフィールドであり PyJWT が自然にサポート**: verify_token() は `kid` を無視して署名検証するため、既存関数を変更せずに multi-agent 対応できた
- **Signer mismatch は「署名は正しいが identity が偽造されている」状態**: 署名検証が成功した後に `sub != key owner` を確認することで、鍵の流出による identity 偽造を検出できる
- **compromised 隔離は「registry の status フラグ」だけで実現できる**: 分散 revocation や KMS は不要。sandbox 範囲では in-memory の status 管理で十分
- **audit の `signer_rejected` に `signature_verified: bool` を含めることで因果が明確になる**: mismatch（署名OK・identity NG）と compromised（署名未確認・鍵NG）を区別して記録できる

### Next Action

- [x] AgentKeyRegistry / SandboxSigner 実装（完了）
- [x] 28件テスト追加、263 passed（完了）
- [ ] EXP-008: Key Rotation / Revocation（revoked 鍵の lifecycle 検証）
- [ ] PyPI 実公開（`python -m build && twine upload`）— Wave 1 残タスク

---

## 次の実験候補

| ID | タイトル | 仮説 | 状態 |
|---|---|---|---|
| EXP-004 | Minimal Sandbox Purchase Flow | 使い捨てトークンだけで安全なAPI購入フローを再現できる | ✅ Completed |
| EXP-005a | Budget Control | SandboxBudgetControl + HTTP 402 + replayable audit | ✅ Completed |
| EXP-005b | JTI Collision | threading.Lock で N スレッド同時送信でも approved=1 を保証 | ✅ Completed |
| EXP-006 | Replay Burst Freeze | FreezeLayer ラッパーで verifier を変えずに burst 検知・freeze | ✅ Completed |
| EXP-005c | Agent Keypair Isolation | JWT kid + AgentKeyRegistry で multi-agent 鍵境界を実現 | ✅ Completed |
| EXP-008 | Key Rotation / Revocation | revoked 鍵の旧トークン拒否・新鍵の受け入れを audit で追跡できる | 📋 設計中 |
| EXP-009 | Distributed Replay Coordination | multi-process 環境での replay 安全性を検証できる | 🔭 候補 |
| EXP-010 | Signer Reputation / Trust Scoring | signer 行動履歴から trust score を構築できる | 🔭 候補 |
