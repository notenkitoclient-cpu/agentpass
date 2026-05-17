# Testing Policy — AgentPass

> 153件のテスト資産は「プロダクト品質の証明書」である。  
> AI エージェントを含む全コントリビューターはこのポリシーに従うこと。

---

## Core Principle

**テスト件数は増やすことしか許可しない。**

```
153 件 → 153 件以上（OK）
153 件 → 152 件以下（NG・理由なき削除は即リジェクト）
```

---

## Test Suite Overview

| ファイル | 件数 | 対象 | 状態 |
|---------|------|------|------|
| `test_token_issuer.py` | 9 | `TokenRequest`, `issue_token`, `generate_keypair` | ✅ |
| `test_token_verifier.py` | 15 | `verify_token`, `VerificationError` 階層 | ✅ |
| `test_circuit_breaker.py` | 22 | `CircuitBreaker`（スライディングウィンドウ・原子性） | ✅ |
| `test_agentpass_crawler.py` | 20 | SSRF・1MB・TTL・HTTP異常・不正JSON・スキーマ検証 | ✅ カバレッジ100% |
| `test_authorization_middleware.py` | 20 | 旧 `merchant/` ミドルウェア（レガシー保護） | ✅ |
| `test_core_authorization_middleware.py` | 18 | `AuthorizationMiddleware`（モック Crawler 注入） | ✅ |
| `test_agent_signer.py` | 9 | `derive_agent_id`（決定論性・UUID形式・唯一性） | ✅ |
| `test_credit_scorer.py` | 22 | `CreditScorer`（境界値・ペナルティ・クリッピング） | ✅ |
| `test_anomaly_detector.py` | 11 | `AnomalyDetector`（リプレイ検知・GC・FakeTime） | ✅ |
| `e2e/test_agentpass_ecosystem.py` | 7 | FastAPI + respx フルスタック統合 | ✅ |
| **合計** | **153** | | |

---

## Coverage Requirements

| モジュール | 必要カバレッジ | 現状 |
|---|---|---|
| `src/core/agentpass_crawler.py` | **100%** | ✅ 100% |
| `src/core/` 全体 | > 80% | 確認要 |
| `src/identity/` 全体 | > 80% | 確認要 |

カバレッジ測定コマンド:
```bash
.venv/bin/pytest tests/test_agentpass_crawler.py tests/e2e/ \
  --cov=src --cov-report=term-missing
```

---

## SSRF Testing Rules

### ⚠️ Python 3.14 の重大な注意点

Python 3.14 では `ipaddress.is_private` の定義が拡大された。

```python
# Python 3.14
import ipaddress
ipaddress.ip_address("203.0.113.1").is_private  # → True（RFC 5737 TEST-NET-3）
ipaddress.ip_address("192.0.2.1").is_private    # → True（RFC 5737 TEST-NET-1）
ipaddress.ip_address("198.51.100.1").is_private # → True（RFC 5737 TEST-NET-2）
```

これらのアドレスは「ドキュメント用」であるが、Python 3.14 ではプライベート扱いになる。  
SSRF テストのモック「公開 IP」として**絶対に使ってはいけない**。

### 正しい SSRF テスト用モック IP

```python
# ✅ OK: Google Public DNS（確実にグローバル）
monkeypatch.setattr(
    socket, "gethostbyname_ex",
    lambda host: (host, [], ["8.8.8.8"])
)

# ✅ OK: Cloudflare DNS
monkeypatch.setattr(
    socket, "gethostbyname_ex",
    lambda host: (host, [], ["1.1.1.1"])
)

# ❌ NG: RFC 5737 / RFC 3849 ドキュメント用アドレス
# 203.0.113.x, 192.0.2.x, 198.51.100.x, 2001:db8::/32
```

### SSRF テストカバレッジ要件（全7パターン）

| テストケース | 対象行 | 実装済み |
|---|---|---|
| loopback IP (127.0.0.1) | `is_loopback` | ✅ |
| プライベート IP (10.x.x.x) | `is_private` | ✅ |
| プライベート IP (192.168.x.x) | `is_private` | ✅ |
| DNS 解決失敗 (`gaierror`) | `except socket.gaierror` | ✅ |
| SSRF 拒否時に HTTP 通信ゼロ | `route.called is False` | ✅ |
| 空 IP リスト | `if not ip_list` | ✅ |
| パース不能 IP 文字列 | `except ValueError` | ✅ |

---

## Replay Attack Testing Rules

### テスト必須パターン

| テストケース | 検証内容 |
|---|---|
| 初回 JTI → Pass | `is_replay_attack` returns `False` |
| 同一 JTI 再送 → Block | `is_replay_attack` returns `True` |
| 3回目以降 → Block | 毎回 `True` |
| 異なる JTI → Pass | 他トークンに影響しない |
| TTL 期限切れ後の GC | 期限切れ JTI がメモリから解放される |

### FakeTime パターン（必須）

```python
class FakeTime:
    def __init__(self, t: float): self.t = t
    def __call__(self): return self.t

fake = FakeTime(1000.0)
detector = AnomalyDetector(_time_func=fake)
# fake.t を変更することで時間経過をシミュレート
```

---

## HTTP Mock Rules (respx)

```python
# ✅ 正しい使い方
async with respx.mock:
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=payload))
    result = await crawler.fetch_merchant_metadata(domain)
    assert route.call_count == 1

# ✅ 例外を発生させる
async with respx.mock:
    respx.get(URL).mock(side_effect=httpx.ConnectError("unreachable"))

# ❌ 禁止: 実際の外部 HTTP 通信
# respx.mock を使わずに httpx を呼び出すテスト
```

---

## Regression Prevention Protocol

新機能追加・リファクタリング後の確認手順:

```bash
# Step 1: 全テスト実行
.venv/bin/pytest --tb=short -q

# Step 2: カバレッジ確認（crawler は 100% 必須）
.venv/bin/pytest tests/test_agentpass_crawler.py \
  --cov=src/core/agentpass_crawler --cov-report=term-missing

# Step 3: E2E 確認
.venv/bin/pytest tests/e2e/ -v

# 全件パスを確認してから作業完了を宣言すること
```

---

## Test Deletion Policy

テストを削除してよい唯一の条件:

1. 対応する実装コードが削除された（非推奨後に実際に削除した場合）
2. 同等以上のカバレッジを持つ別テストで完全に置き換えた
3. 削除理由を PR 説明に明記した

**判断できない場合はテストを残す。**

---

## Adding New Tests

新機能追加時のテスト要件:

```
1. 正常系（happy path）: 最低1件
2. 境界値: 入力の境界を1件以上
3. 異常系: 期待する例外を1件以上
4. セキュリティ関連機能: 各防衛パターンを網羅
```

セキュリティ機能（SSRF・リプレイ・1MB制限）は **すべての防衛分岐** をテストすること。

---

## Python 3.14 Considerations

| 項目 | 注意点 |
|------|--------|
| `ipaddress.is_private` | RFC 5737/3849 アドレスも private 扱いになった |
| `asyncio` | デフォルトイベントループポリシーに変更あり（`asyncio_mode="auto"` で対処済み） |
| `match` 文 | Python 3.10+ 構文として使用可 |

---

## TODO

- [ ] `src/core/` 全体のカバレッジを計測・記録する
- [ ] カバレッジバッジを README に追加する
- [ ] GitHub Actions でカバレッジ閾値チェックを追加する（80% 未満でCI失敗）
- [ ] ミューテーションテスト（`mutmut`）の導入を検討する
