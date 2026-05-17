# AI Instructions — AgentPass Project

> Claude Code / Codex / ChatGPT / Gemini CLI 共通運用ルール。  
> このファイルを読んだ AI エージェントはすべてのルールに従うこと。

---

## 0. CRITICAL RULES（最優先）

```
1. 153件のテストを壊さない（テスト件数の減少は許可しない）
2. 既存テストのインポートパス（from src.core.xxx）を変更しない
3. src/merchant/ は旧設計。触れるな。新規コードは src/core/ か src/identity/ に書く
4. テストをスキップ・削除・コメントアウトするな
5. セキュリティ境界（SSRF・リプレイ攻撃防御）を弱体化するな
```

---

## 1. Architecture Rules

### パッケージ構造
```
src/agentpass/  → 公開 API のみ（__init__.py の __all__ 管理）
src/core/       → コア実装（新機能はここ）
src/identity/   → アイデンティティ実装（AgentID・信用スコア）
src/merchant/   → 旧設計。読み取り専用。新コードを置くな
tests/          → テストのみ。実装コードを置くな
```

### import パターン
```python
# 開発中（テスト内）
from src.core.xxx import Yyy          # OK — テスト標準パターン
from agentpass import Yyy             # OK — src/ が pythonpath に追加済み

# src/agentpass/__init__.py 内
from core.xxx import Yyy              # OK — package-dir={"":"src"} 前提

# 禁止
from src.merchant.xxx import Yyy      # NG — 旧設計
import src.merchant.xxx               # NG — 旧設計
```

---

## 2. Coding Rules

### 全般
- Python 3.13+ 構文を使用（`X | Y` union、`match`文 など）
- `from __future__ import annotations` を各モジュール冒頭に記述
- 型アノテーション必須（`-> None` も省略しない）
- コメントは「WHY」のみ。「WHAT」はコードから自明にする

### データクラス
```python
# 不変データは frozen=True
@dataclass(frozen=True)
class MyData:
    field: str
```

### 例外
```python
# VerificationError 系は http_status と error_code を持つ
class MyError(VerificationError):
    http_status = 400
    error_code = "MY_ERROR_CODE"
```

### 非同期
- `async def` + `await` を使用
- `asyncio.run()` は `if __name__ == "__main__"` 内のみ
- テストは `asyncio_mode = "auto"` 済み（`@pytest.mark.asyncio` 不要）

---

## 3. Testing Rules

### 必須ルール
```
- 新機能を追加したら、対応するテストを追加する
- テストを追加しても減らすな（153 → 153以上を維持）
- モックは monkeypatch か respx を使用
- 外部 HTTP 通信は respx でモック（CI で実通信させるな）
- 時刻依存処理は _time_func 注入パターンで制御
```

### テストファイル命名
```
tests/test_{module_name}.py            # 単体テスト
tests/test_core_{module_name}.py       # core/ 層のテスト
tests/e2e/test_{scenario_name}.py      # E2E テスト
```

### SSRF テストの注意点
```python
# NG: RFC 5737 TEST-NET-3 は Python 3.14 で is_private=True
monkeypatch.setattr(socket, "gethostbyname_ex", lambda h: (h, [], ["203.0.113.1"]))

# OK: Google Public DNS は is_private=False
monkeypatch.setattr(socket, "gethostbyname_ex", lambda h: (h, [], ["8.8.8.8"]))
```

### カバレッジ
```bash
# core/agentpass_crawler.py は 100% を維持すること
.venv/bin/pytest tests/test_agentpass_crawler.py --cov=src --cov-report=term-missing
```

---

## 4. Security Rules

### SSRF 防御（変更禁止）
- `socket.gethostbyname_ex` でDNS解決してからHTTP接続
- プライベートIP・ループバック・リンクローカル・予約済み・マルチキャスト・未指定 → 即拒否
- DNS 解決失敗・空 IP リスト・パース不能 IP → 即拒否
- 拒否時は HTTP 通信をゼロにすること

### リプレイ攻撃防御（変更禁止）
- `jti` + `AnomalyDetector` による二重防御
- `AnomalyDetector.is_replay_attack(jti, exp)` のシグネチャを変更するな
- JTI は期限（exp）まで保持・期限後はGCで解放

### トークン検証順序（変更禁止）
```
1. 署名 → InvalidPayloadError (400)
2. 有効期限 → TokenExpiredError (401)
3. 宛先URL → DestinationMismatchError (403)
```

### 1MB ストリーム制限（変更禁止）
- `max_bytes` のデフォルト: 1,048,576 bytes
- チャンク単位で累積チェック（一括読み込み禁止）
- 超過時は即切断（`ValueError: Security Boundary Exceeded`）

---

## 5. Naming Rules

| 対象 | 規則 | 例 |
|------|------|-----|
| クラス | UpperCamelCase | `AuthorizationMiddleware` |
| 関数・メソッド | snake_case | `verify_token()` |
| 定数 | UPPER_SNAKE_CASE | `WINDOW_SECONDS = 60` |
| プライベート | `_` prefix | `_is_private_ip()` |
| テスト関数 | `test_` prefix + 動詞 | `test_crawler_ssrf_protection_loopback` |
| テストクラス | `Test` prefix + 名詞 | `TestCrawlerSsrfProtection` |
| 型エイリアス | UpperCamelCase | `CacheEntry = tuple[float, MerchantMetadata]` |

---

## 6. Backward Compatibility Policy

### 変更してよいもの
- 新しいオプション引数の追加（デフォルト値あり）
- `src/agentpass/__init__.py` への新シンボルの追加
- テストの追加

### 変更禁止
- `VerifiedClaims` のフィールドの削除・リネーム
- `TokenRequest` の必須フィールドの削除・変更
- `verify_token()`, `issue_token()` のシグネチャの破壊的変更
- エラーコード文字列の変更（`INVALID_PAYLOAD` 等）
- `agentpass.json` スキーマの後方非互換変更

### 非推奨化プロセス
```
1. 旧 API に @deprecated デコレータ追加
2. 1 バージョン以上の deprecation warning 期間
3. メジャーバージョンで削除
```

---

## 7. PyPI / Package Rules

- `src/agentpass/__init__.py` の `__all__` を常に最新に保つ
- 新しい公開シンボルを追加したら `__all__` に追加
- `__version__` は `pyproject.toml` の `version` と同期すること
- `src/merchant/` は `exclude = ["merchant*"]` で配布から除外済み

---

## 8. AI Agent Behavior Protocol

```
セッション開始時:
  1. MEMORY.md を読む
  2. project_agentpass_progress.md を読む
  3. pytest を実行して現状確認（153件以上パスすること）

コード変更前:
  1. 変更対象ファイルを Read する
  2. 影響する下流ファイルを確認する
  3. テスト数が減らないことを確認する

コード変更後:
  1. .venv/bin/pytest を実行
  2. 全件パスを確認してから報告する
  3. 進捗を memory/ に記録する

禁止行動:
  - テストが失敗したまま「完了」と報告すること
  - --no-verify, -k "not xxx" など制限フラグでごまかすこと
  - 未確認の前提でコードを書くこと（必ず Read してから）
```
