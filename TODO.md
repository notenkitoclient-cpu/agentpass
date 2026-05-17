# AgentPass MVP — 開発チェックリスト

> 実装言語: **Python 3.14 / pytest** （TypeScript案から変更）
> `ai-instructions.md` を必ず先に読んでから各タスクに着手してください。

---

## 前提確認（Day 1-2）

- [x] `ai-instructions.md` を全文読み込んだか
- [x] トークンのJSONスキーマ（セクション2）を理解したか
- [x] サーキットブレーカーの閾値（セクション3）を確認したか
- [x] Python 3.14 + venv 環境を構築したか

---

## Week 1: コア決済 & サーキットブレーカー（安全弁） ✅ M1達成

### 実装済み
- [x] `src/core/token_issuer.py` — Ed25519署名付き使い捨てJWT発行
  - ペイロード仕様：`ai-instructions.md` セクション2.3に完全準拠
  - `PyJWT` + `cryptography` を使用
- [x] `src/core/token_verifier.py` — トークンのデコードと3段階検証
  - 署名検証（400）/ 期限切れ（401）/ 宛先不一致（403）
  - `jti` クレームで重複使用（リプレイ攻撃）を防止
- [x] `src/core/circuit_breaker.py` — 予算制限・レートリミット
  - スライディングウィンドウ方式（60秒）
  - `BudgetExceededError` (429) / `RateLimitedError` (429)
  - 時刻注入（`_time_func`）でsleepなしのテストを実現

### テスト済み（46件 / 全パス）
- [x] `tests/test_token_issuer.py` — 9件
- [x] `tests/test_token_verifier.py` — 15件
- [x] `tests/test_circuit_breaker.py` — 22件

### クロスチェック
- [x] **マイルストーンM1達成：** 使い捨てトークンが安全に発行・検証・予算制限できる状態

---

## Week 2: 加盟店接続インフラ（.well-known） ✅ M2達成（再設計版）

### 実装済み（旧 merchant/ モジュール）
- [x] `src/merchant/agentpass_crawler.py` — urllib ベース同期クローラー（初期版）
- [x] `src/merchant/authorization_middleware.py` — 直接公開鍵注入版ミドルウェア（初期版）

### 実装済み（新 core/ モジュール — httpx 非同期・iss クレーム対応版）
- [x] `src/core/agentpass_crawler.py` — `httpx.AsyncClient` ストリーミング非同期クローラー
  - 3層防御：1MB 超即切断 → JSON パース → Pydantic v2 スキーマ検証
  - `_MAX_BYTES = 1MB`, `_TIMEOUT = 5.0s`, `_SUPPORTED_VERSION = "1.0.0"`
  - `MerchantMetadata.public_key_hex` プロパティで HEX 変換を隠蔽
- [x] `src/core/authorization_middleware.py` — iss クレーム自律公開鍵取得版ミドルウェア
  - `Authorization: AgentPass <token>` スキームを厳格検証（大文字小文字区別）
  - 署名検証なし JWT デコードで `iss` を先行抽出 → `AgentPassCrawler` で公開鍵取得
  - `request.state.agent_claims` に `VerifiedClaims` をバインド
  - `crawler=` 引数でモック注入対応（テスト容易性）
  - エラーコード体系：401/400/503/401/403 を明記した JSON 早期返却

### テスト済み（38件追加 / 累計 178件）
- [x] `tests/test_agentpass_crawler.py` — 26件（旧 merchant モジュール）
- [x] `tests/test_authorization_middleware.py` — 20件（旧 merchant モジュール）
- [x] `tests/test_core_agentpass_crawler.py` — 20件（respx・外部通信ゼロ・3層防御）
- [x] `tests/test_core_authorization_middleware.py` — 18件（モッククローラー注入・全エラーパス網羅）

### クロスチェック
- [x] **マイルストーンM2達成：** JSON1枚設置だけで決済を待ち受けられるか
- [x] **再設計完了：** iss クレームから公開鍵を自律取得する非同期フローが全テスト通過

---

## Week 3: AgentID（認証・信用スコアリング） ✅ M3達成（再設計版）

### 実装済み
- [x] `src/identity/agent_signer.py` — Ed25519公開鍵（32バイト）からの決定論的ID派生
  - `derive_agent_id(public_key_bytes: bytes) -> str`
  - SHA-256ハッシュの先頭16バイトをUUID形式に変換（同一入力→同一出力保証）
- [x] `src/identity/credit_scorer.py` — M2M自律信用スコアリングエンジン
  - `CreditScorer.calculate_score(age_days, success_count, error_rate, budget_overflow_count) -> float`
  - スコール範囲: 0.0〜100.0（基本スコア100から加点・ペナルティ乗数で変動）
  - エラーペナルティ乗数: max(0.1, 1.0 - error_rate*0.5)
  - 予算超過ペナルティ乗数: max(0.1, 1.0 - overflow_count*0.2)
  - 最終出力は 0.0〜100.0 にクリップ

### テスト済み（31件 / 累計 161件）
- [x] `tests/test_agent_signer.py` — 9件（UUID形式・決定論性・一意性）
- [x] `tests/test_credit_scorer.py` — 22件（クリーン状態・エラーペナルティ・予算超過ペナルティ・クリップ・複合）

### クロスチェック
- [x] **マイルストーンM3達成：** エージェントIDを決定論的に生成し、信用スコアで動的評価できる

---

## Week 4: エコシステム統合とE2E・アノマリー防御 ✅ M4達成

### 実装済み
- [x] `src/core/anomaly_detector.py` — JTI ベースリプレイ攻撃検知
  - `AnomalyDetector.is_replay_attack(jti, exp) -> bool`
  - インメモリ辞書（`dict[str, float]`）で既使用 JTI を管理
  - 毎呼び出し時に有効期限切れエントリを GC（メモリ肥大化防止）
  - `_time_func` 注入で sleep なしのテスト設計
- [x] `src/core/authorization_middleware.py` 拡張 — AnomalyDetector 統合
  - `AuthorizationMiddleware(anomaly_detector=...)` オプション追加（後方互換）
  - verify_token 成功後にリプレイチェック → 検知時 403 REPLAY_ATTACK

### テスト済み（18件追加 / 累計 179件）
- [x] `tests/test_anomaly_detector.py` — 11件（初回False・リプレイTrue・GC）
- [x] `tests/e2e/test_agentpass_ecosystem.py` — 7件（FastAPI + respx フルスタックE2E）
  - 正常系: 有効トークン → 200、agent_claims バインド確認、異なるJTI → 両方200
  - 異常系（リプレイ）: 同一トークン再送 → 403 REPLAY_ATTACK、3回目以降も同様、他トークンへの影響なし

### 最終確認チェック
- [x] 予算超過リクエストでサーキットブレーカーが作動するか（Week 1 test_circuit_breaker.py）
- [x] トークン再利用でリプレイ攻撃が防止されるか（test_anomaly_detector.py・E2E）
- [x] フルスタックE2EでM2M決済フローが完結するか（test_agentpass_ecosystem.py）
- [x] **マイルストーンM4達成：** ファースト・トランザクション成功（E2E 正常系）

---

## ディレクトリ構造（現在 — 全 Week 完了）

```
AgentPass/
├── ai-instructions.md          ← AIエージェント向け仕様書（読み込み必須）
├── TODO.md                     ← このファイル
├── STRATEGY.md                 ← 3ホライゾン戦略ロードマップ
├── SPIDERMAP.md                ← 事業全体像スパイダーマップ
├── pyproject.toml
├── src/
│   ├── core/                   ✅ Week 1〜4 全コアモジュール
│   │   ├── token_issuer.py           (Week 1) JWT 発行
│   │   ├── token_verifier.py         (Week 1) 署名・期限・宛先 3段階検証
│   │   ├── circuit_breaker.py        (Week 1) 予算・レート制限
│   │   ├── agentpass_crawler.py      (Week 2) httpx 非同期 3層防御クローラー
│   │   ├── authorization_middleware.py(Week 2+4) iss 自律公開鍵取得 + リプレイ防御
│   │   └── anomaly_detector.py       (Week 4) JTI インメモリ GC 付きリプレイ検知
│   ├── merchant/               ⚠️ 初期版（旧設計・参照専用）
│   │   ├── agentpass_crawler.py      urllib 同期版（非推奨）
│   │   └── authorization_middleware.py 直接公開鍵注入版（非推奨）
│   └── identity/               ✅ Week 3 完了
│       ├── agent_signer.py           Ed25519 公開鍵 → 決定論的 UUID
│       └── credit_scorer.py          スコア範囲 0.0〜100.0 乗数ペナルティ型
├── tests/
│   ├── test_token_issuer.py                   ✅  9件  (Week 1)
│   ├── test_token_verifier.py                 ✅ 15件  (Week 1)
│   ├── test_circuit_breaker.py                ✅ 22件  (Week 1)
│   ├── test_agentpass_crawler.py              ✅ 26件  (旧 merchant/ — 参照専用)
│   ├── test_authorization_middleware.py       ✅ 20件  (旧 merchant/ — 参照専用)
│   ├── test_core_agentpass_crawler.py         ✅ 20件  (Week 2 新 core/)
│   ├── test_core_authorization_middleware.py  ✅ 18件  (Week 2 新 core/)
│   ├── test_agent_signer.py                   ✅  9件  (Week 3)
│   ├── test_credit_scorer.py                  ✅ 22件  (Week 3)
│   ├── test_anomaly_detector.py               ✅ 11件  (Week 4)
│   ├── e2e/
│   │   └── test_agentpass_ecosystem.py        ✅  7件  (Week 4 FastAPI+respx E2E)
│   └── mocks/                                 （空・将来の加盟店モック用）
│                                          ─────────────────────
│                                          合計  179件 全パス
└── .well-known/
    └── agentpass.json          ← AgentPass自身の加盟店設定
```

---

*最終更新：2026-05-16 | Week 1〜4 完了・M1〜M4 全マイルストーン達成 / 179件全テスト通過*
