# Contributing to AgentPass

> OSS 化を前提とした貢献ガイドライン。  
> AI エージェントを含む全コントリビューターへ適用する。

---

## Quick Start for Contributors

```bash
# 1. リポジトリのクローン
git clone https://github.com/your-org/agentpass.git
cd agentpass

# 2. 仮想環境のセットアップ
python3.13 -m venv .venv
source .venv/bin/activate

# 3. 依存関係のインストール
pip install -e ".[dev]"

# 4. テストの実行
pytest
# → 153件以上 all pass を確認してから開始
```

---

## Branch Policy

| ブランチ | 用途 | 直接 push |
|---|---|---|
| `main` | リリース済み安定版 | ❌ PR のみ |
| `develop` | 開発統合ブランチ | ❌ PR のみ |
| `feature/*` | 新機能開発 | ✅ 本人のみ |
| `fix/*` | バグ修正 | ✅ 本人のみ |
| `security/*` | セキュリティ修正 | ✅ 本人のみ・非公開で作業 |
| `experiment/*` | PoC・検証 | ✅ 本人のみ |

### ブランチ命名規則
```
feature/add-multi-currency-support
fix/ssrf-ipv6-edge-case
security/replay-attack-ttl-improvement
experiment/wave2-credit-score-api-poc
```

---

## Pull Request Rules

### PR 作成前チェックリスト
```
□ .venv/bin/pytest → 153件以上全パス
□ カバレッジ確認（core/agentpass_crawler.py は 100% 必須）
□ 新機能には対応テストを追加した
□ セキュリティ境界を弱体化していない
□ 既存の公開 API（__all__ のシンボル）を破壊的に変更していない
□ src/merchant/ を変更していない（参照専用）
```

### PR テンプレート
```markdown
## What

何を変更したか。1〜3文で。

## Why

なぜ変更したか。課題・背景。

## How

どう実装したか。主要な設計判断。

## Testing

- テスト件数: 153 → XXX
- 新規追加テスト: tests/test_xxx.py (N件)
- カバレッジ: XXX%

## Breaking Changes

なし / あり（あれば詳細を記述）

## Security Considerations

セキュリティへの影響（SSRF・リプレイ・1MB制限等）
```

---

## Testing Requirements

### 必須
- `pytest` → **全件パス**（件数減少 NG）
- 新機能には正常系・境界値・異常系を各1件以上追加
- セキュリティ機能は全防衛分岐を網羅

### SSRF テスト
```python
# モック公開 IP は必ず 8.8.8.8 を使用（Python 3.14 対応）
monkeypatch.setattr(socket, "gethostbyname_ex", lambda h: (h, [], ["8.8.8.8"]))
```

### HTTP モック
```python
# 外部通信は respx でモックする（実通信禁止）
async with respx.mock:
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))
```

---

## Coding Convention

### ファイル構成
```python
"""
モジュール説明（1〜2文）
"""

from __future__ import annotations

# 標準ライブラリ
import os

# サードパーティ
import httpx

# 内部
from src.core.xxx import Yyy
```

### 型アノテーション
```python
# ✅ OK
def verify(token: str, key: Ed25519PublicKey) -> VerifiedClaims: ...

# ❌ NG
def verify(token, key): ...
```

### エラーハンドリング
```python
# ✅ OK — 具体的な例外クラスを使用
except jwt.ExpiredSignatureError as exc:
    raise TokenExpiredError("Token has expired") from exc

# ❌ NG — 汎用 except
except Exception:
    pass
```

---

## Security Policy

### 脆弱性の報告

セキュリティ脆弱性を発見した場合:

1. **GitHub Issues には報告しない**（公開になるため）
2. `security@agentpass.example.com` に報告（TODO: 実際のアドレスに更新）
3. 報告内容:
   - 脆弱性の概要
   - 再現手順
   - 影響範囲
   - 推奨される修正方法

### 禁止事項
- SSRF 防御の弱体化・迂回
- リプレイ攻撃防御の削除・削減
- 1MB ストリーム制限の撤廃
- `jti` チェックのスキップ可能化
- プライベート IP ホワイトリスト機能の追加

---

## Commit Message Rules

```
<type>(<scope>): <description>

type:
  feat     — 新機能
  fix      — バグ修正
  security — セキュリティ修正
  test     — テスト追加・修正
  docs     — ドキュメント
  refactor — リファクタリング（機能変更なし）
  chore    — ビルド・CI・設定

scope（省略可）:
  crawler, middleware, verifier, issuer, circuit-breaker, anomaly, identity

例:
  feat(crawler): add force_refresh parameter to bypass TTL cache
  security(ssrf): block empty IP list from gethostbyname_ex
  test(crawler): achieve 100% coverage for _is_private_ip branches
  fix(verifier): preserve error chain with 'from exc' in TokenExpiredError
```

---

## AI Agent Contribution Guidelines

Claude Code, ChatGPT, Codex, Gemini CLI による自動貢献ルール:

```
必須:
  - 変更前に Read ツールでファイルを確認する
  - 変更後に pytest を実行して全件パスを確認する
  - セキュリティ機能を変更する場合は、変更理由を明示する

禁止:
  - テスト失敗のまま「完了」と報告する
  - --no-verify や -k "not xxx" でテストを迂回する
  - src/merchant/ に新しいコードを追加する
  - 153件未満のテスト件数で PR を作成する
```

---

## Release Process

```bash
# 1. バージョン更新
# pyproject.toml の version を更新
# src/agentpass/__init__.py の __version__ を同期

# 2. CHANGELOG.md を更新（TODO: 作成）

# 3. テスト最終確認
pytest && echo "All tests pass"

# 4. ビルド
python -m build

# 5. TestPyPI で確認
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ agentpass

# 6. 本番 PyPI
twine upload dist/*
```

---

## TODO

- [ ] `security@agentpass.example.com` の実際のアドレス設定
- [ ] GitHub Actions CI/CD の整備（PR 時の自動 pytest）
- [ ] `CHANGELOG.md` の作成
- [ ] コードオーナー（CODEOWNERS）ファイルの作成
- [ ] Issue テンプレートの作成（bug report / feature request）
