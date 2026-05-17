# MASTER STATUS — AgentPass AI Operations OS

> **このファイルはAgentPassの「唯一の現在地」です。**
>
> - 各チャット・各AIエージェントは会話開始時に必ずこのファイルを参照する
> - 会話履歴・記憶・推測よりも、このファイルの記載を真実とする
> - 大きな状態変化が起きたら、会話終了前にこのファイルを更新する

---

## CURRENT STATE ID

```
STATE-2026-05-17-EXP004-COMPLETE
```

**意味:** EXP-004（Minimal Sandbox Purchase Flow）が全成功基準を達成して完了した状態。
次の優先事項は EXP-005 の設計開始。

---

## CURRENT PHASE

```
STEP9 — Sandbox Runtime Validation
```

Wave 1（エコシステム・パッケージング）は完了。
現在は Wave 2 の入口として Sandbox 実験で実用性を検証するフェーズ。

---

## CURRENT ACTIVE EXPERIMENT

```
EXP-004: Minimal AgentPass Sandbox Purchase Flow — ✅ COMPLETED
```

| 項目 | 結果 |
|------|------|
| Attempt 1 (fresh token) | 200 Access granted ✓ |
| Attempt 2 (same token) | 401 Replay attack detected ✓ |
| audit_exp004.jsonl | 2行保存済み ✓ |
| 153 tests | 全通過 ✓ |
| exit code | 0 ✓ |

実装済みファイル:
- `examples/sandbox_merchant.py`
- `examples/sandbox_agent.py`

---

## CURRENT PRIORITY

```
EXP-005: Budget-limited autonomous purchase flow (設計開始)
```

**仮説:** CircuitBreaker による予算上限制御下でも、エージェントの購入フローは正常完了する。
また、予算超過時は `BudgetExceededError` が適切に発火する。

**前提:** EXP-004 が確立した基盤（token issue → verify → replay detect）の上に構築する。

---

## CURRENT BRANCH

```
experiment/exp-004-sandbox-merchant
```

このブランチには以下が含まれる（未マージ・未push確認状態）:
- `examples/sandbox_merchant.py`
- `examples/sandbox_agent.py`
- `.gitignore` 更新（sandbox_keys.json, audit_exp*.jsonl を除外）
- `AI運営OS用/docs/EXPERIMENT_LOG.md` EXP-004 結果記入

**次のアクション:** `main` へのPR作成、またはEXP-005ブランチへ移行。

---

## CURRENT FOCUS

- [x] Sandbox での replay detection 検証（完了）
- [x] JSONL audit log 保存（完了）
- [ ] EXP-005: CircuitBreaker 連携での予算制御実験（次）
- [ ] Wave 2 課題: agent 独自鍵ペアと merchant 側公開鍵レジストリ設計
- [ ] `core/__init__.py` 遅延インポート検討（スクリプト実行時の重さ対策）

---

## LATEST DECISIONS

| ID | タイトル | 状態 | 要点 |
|----|---------|------|------|
| Decision 001 | ChatGPT Projects を運営OS として使う | ACTIVE | このファイルはその版管理鏡 |
| Decision 002 | AI運営OS用/docs/ を既存docsと分離 | ACTIVE | 既存コード・テストは変更しない |
| Decision 003 | main保護とCIを優先 | ACTIVE | `.github/workflows/ci.yml` 稼働中 |
| Decision 004 | 153 tests を壊さない方針 | ACTIVE | CI が強制; floor=153 |
| Decision 005 | Sandbox実験を次フェーズの中心にする | ACTIVE | EXP-004 完了で実証済み |

詳細: `DECISIONS.md`

---

## CURRENT RISKS

| リスク | 重要度 | 現状 |
|--------|--------|------|
| マルチエージェント競合未検証 | 高 | EXP-006 候補。同一JTI並列送信でのAnomalyDetector挙動が未テスト |
| 予算制御 (CircuitBreaker) 未検証 | 高 | EXP-005 で検証予定。現sandbox に組み込まれていない |
| agent 独自鍵ペア管理未設計 | 中 | EXP-004 では merchant/agent が同一鍵ペアを共有（sandbox の簡略化） |
| `core/__init__.py` の重いインポート | 低 | スクリプト実行時に不要モジュールまで読み込む。Wave 2 前に整理検討 |
| PyPI 未公開 | 低 | `v1.0.0-beta1` パッケージング済みだが `twine upload` 未実行 |
| GitHub ブランチ保護ルール未設定 | 中 | CI は稼働しているが、GitHub UI 側の PR 必須化が未設定 |

---

## CURRENT OWNERS

| チャンネル | 役割 | 担当領域 |
|-----------|------|---------|
| **Sandbox実験室** | 実装・実験 | EXP-004〜 の sandbox スクリプト実装・実行 |
| **技術相談室** | 設計・判断 | アーキテクチャ決定・リスク評価・Wave 2 設計 |
| **Claude Code (このセッション)** | コーディング | src/ tests/ examples/ の実装補助 |

---

## NEXT REQUIRED ACTION

```
[1] EXP-004 ブランチを main へ PR（またはマージ）
[2] EXP-005 設計開始: Budget-limited autonomous purchase flow
    → examples/sandbox_merchant_v2.py に CircuitBreaker を組み込む
    → 成功: 購入フロー完走, 失敗: BudgetExceededError で 402 返却
```

詳細手順は `EXPERIMENT_LOG.md` の「次の実験候補」テーブルを参照。

---

## NEXT RESPONSIBLE CHANNEL

```
Sandbox実験室
```

EXP-005 の設計・実装は Sandbox実験室が主導。
`CLAUDE_CODE_WORKFLOW.md` の Template C（Sandbox実験用）を使って Claude Code に依頼可能。

---

## LAST UPDATED

```
2026-05-17T02:15:00Z
```

---

## STATE ID ルール

### 形式

```
STATE-YYYY-MM-DD-KEYWORD[-KEYWORD2]
```

### 例

| STATE ID | 意味 |
|----------|------|
| `STATE-2026-05-17-EXP004-COMPLETE` | EXP-004 完了 |
| `STATE-2026-05-17-EXP005-RUNNING` | EXP-005 実行中 |
| `STATE-2026-05-18-DECISION006` | Decision 006 が追加された |
| `STATE-2026-05-20-WAVE2-START` | Wave 2 フェーズ開始 |
| `STATE-2026-06-01-PYPI-PUBLISHED` | PyPI 公開完了 |

### 更新タイミング

STATE ID を更新すべき状態変化:

| イベント | 更新する | しない |
|---------|---------|--------|
| Experiment 完了 (`✅ Completed`) | ✓ | |
| Experiment 開始 (`🔄 Running`) | ✓ | |
| Decision 追加・変更 | ✓ | |
| Phase 変更 (STEP番号変更) | ✓ | |
| Priority 変更 | ✓ | |
| Branch 変更（main マージ後）| ✓ | |
| 小さいコミット・docs修正 | | ✓ |
| 単一ファイルの追加 | | ✓ |
| テストの追加 | | ✓ |

---

## 各チャットの運用ルール

### 会話開始時

```
1. このファイル (MASTER_STATUS.md) を読む
2. CURRENT STATE ID を確認する
3. STATE ID が古い（今日の日付と乖離がある、または知らないEXPになっている）場合：
   → 「STATE IDが [X] ですが、これは最新ですか？」と確認を促す
4. CURRENT BRANCH を確認し、git branch で一致を確認する
5. NEXT REQUIRED ACTION を読んで今日のゴールを把握する
```

### 会話中

```
- CURRENT FOCUS のチェックボックスを更新判断の基準にする
- 新しいリスクを発見したら CURRENT RISKS に追記する
- Decision が変わったら LATEST DECISIONS を更新する
```

### 会話終了時

```
1. 以下のいずれかが起きたか確認する:
   - Experiment 完了したか？
   - Decision が追加・変更されたか？
   - Priority が変わったか？
   - Branch が変わったか？
   - Phase が変わったか？

2. 該当するなら MASTER_STATUS.md を更新する:
   a. CURRENT STATE ID を新しい STATE に変更
   b. 該当セクションを更新
   c. LAST UPDATED を現在時刻に更新
   d. git commit -m "status: update MASTER_STATUS → STATE-YYYY-MM-DD-KEYWORD"

3. 更新が不要でも、今日の作業を CHANGELOG.md に追記することを検討する
```

### STATE ID の読み方（AI エージェント向け）

```python
# AI がこのファイルをパースする場合の参照順序:
# 1. CURRENT STATE ID  → 現在地の一行サマリー
# 2. NEXT REQUIRED ACTION → 次にやること
# 3. CURRENT BRANCH → git checkout の対象
# 4. CURRENT RISKS → 回避すべき落とし穴
# 5. LATEST DECISIONS → 守るべき制約
```

---

## 関連ドキュメント

| ファイル | 用途 |
|---------|------|
| `DECISIONS.md` | 意思決定の詳細と根拠 |
| `EXPERIMENT_LOG.md` | 実験の仮説・結果・学習 |
| `CHANGELOG.md` | 変更履歴（時系列） |
| `CLAUDE_CODE_WORKFLOW.md` | Claude Code への作業指示テンプレート |
| `TESTING_POLICY.md` | テストルール（153テスト保護、SSRF mock IP等） |
| `ROADMAP.md` | Wave 1/2/3 のマクロ計画 |
