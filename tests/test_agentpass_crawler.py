"""
src/core/agentpass_crawler.py のテスト

4層の防衛線（SSRF防御・1MBストリーム制限・HTTP異常系・TTLキャッシュ）を検証する。
respx で httpx 通信をモック。asyncio_mode = "auto" により @pytest.mark.asyncio は省略。
"""

from __future__ import annotations

import json as _json
import socket
import uuid

import httpx
import pytest
import respx

from src.core.agentpass_crawler import AgentPassCrawler, MerchantMetadata

BASE_DOMAIN = "agent.example.com"
METADATA_URL = f"https://{BASE_DOMAIN}/.well-known/agentpass.json"


# ---------------------------------------------------------------------------
# テスト用ユーティリティ
# ---------------------------------------------------------------------------

def _valid_payload(**overrides) -> dict:
    """バリデーションを通過する最小限の agentpass.json ペイロードを返す。"""
    base = {
        "agentpass_version": "1.0.0",
        "merchant_id": str(uuid.uuid4()),
        "public_key": "ab" * 32,           # 64-char hex（32 bytes Ed25519）
        "pricing": [{"endpoint": "/api/data", "price_per_token": 0.001}],
    }
    base.update(overrides)
    return base


def _mock_public_dns(monkeypatch) -> None:
    """DNS をパブリック IP に固定して SSRF チェックを通過させる。"""
    monkeypatch.setattr(
        socket,
        "gethostbyname_ex",
        lambda host: (host, [], ["8.8.8.8"]),   # Google Public DNS — 確実にグローバル
    )


# ---------------------------------------------------------------------------
# 正常系 — 取得 + キャッシュ検証
# ---------------------------------------------------------------------------

class TestCrawlerSuccessAndCacheHit:
    async def test_crawler_success_and_cache_hit(self, monkeypatch):
        """
        初回は HTTP モックを 1 回叩き、2 回目はキャッシュから即返すこと（通信 0 回目）。
        """
        _mock_public_dns(monkeypatch)
        crawler = AgentPassCrawler()
        payload = _valid_payload()

        async with respx.mock:
            route = respx.get(METADATA_URL).mock(
                return_value=httpx.Response(200, json=payload)
            )
            result1 = await crawler.fetch_merchant_metadata(BASE_DOMAIN)
            result2 = await crawler.fetch_merchant_metadata(BASE_DOMAIN)

        assert isinstance(result1, MerchantMetadata)
        assert result1.merchant_id == result2.merchant_id
        assert route.call_count == 1         # 2 回目はキャッシュヒット → HTTP 通信なし

    async def test_force_refresh_bypasses_cache(self, monkeypatch):
        """force_refresh=True の場合、キャッシュを無視して再取得すること。"""
        _mock_public_dns(monkeypatch)
        crawler = AgentPassCrawler()
        payload = _valid_payload()

        async with respx.mock:
            route = respx.get(METADATA_URL).mock(
                return_value=httpx.Response(200, json=payload)
            )
            await crawler.fetch_merchant_metadata(BASE_DOMAIN)
            await crawler.fetch_merchant_metadata(BASE_DOMAIN, force_refresh=True)

        assert route.call_count == 2         # force_refresh でキャッシュ無視

    async def test_metadata_fields_parsed_correctly(self, monkeypatch):
        """取得したメタデータのフィールドが正しくパースされること。"""
        _mock_public_dns(monkeypatch)
        payload = _valid_payload()
        crawler = AgentPassCrawler()

        async with respx.mock:
            respx.get(METADATA_URL).mock(return_value=httpx.Response(200, json=payload))
            result = await crawler.fetch_merchant_metadata(BASE_DOMAIN)

        assert result.agentpass_version == "1.0.0"
        assert result.pricing[0].price_per_token == pytest.approx(0.001)
        assert result.pricing[0].endpoint == "/api/data"

    async def test_expired_cache_triggers_refresh(self, monkeypatch):
        """TTL 切れのキャッシュは再取得されること（ttl_seconds=0 で即期限切れ）。"""
        _mock_public_dns(monkeypatch)
        crawler = AgentPassCrawler(ttl_seconds=0)   # 即期限切れ
        payload = _valid_payload()

        async with respx.mock:
            route = respx.get(METADATA_URL).mock(
                return_value=httpx.Response(200, json=payload)
            )
            await crawler.fetch_merchant_metadata(BASE_DOMAIN)
            await crawler.fetch_merchant_metadata(BASE_DOMAIN)

        assert route.call_count == 2         # TTL=0 なので両回とも HTTP 通信


# ---------------------------------------------------------------------------
# 異常系 — SSRF 防御
# ---------------------------------------------------------------------------

class TestCrawlerSsrfProtection:
    async def test_crawler_ssrf_protection_loopback(self, monkeypatch):
        """127.0.0.1 に解決されるドメインは ValueError（"SSRF Protection"）を投げること。"""
        monkeypatch.setattr(
            socket, "gethostbyname_ex", lambda host: (host, [], ["127.0.0.1"])
        )
        crawler = AgentPassCrawler()
        with pytest.raises(ValueError, match="SSRF Protection"):
            await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_crawler_ssrf_protection_private_10(self, monkeypatch):
        """10.x.x.x（プライベート）に解決される場合も ValueError を投げること。"""
        monkeypatch.setattr(
            socket, "gethostbyname_ex", lambda host: (host, [], ["10.0.0.1"])
        )
        crawler = AgentPassCrawler()
        with pytest.raises(ValueError, match="SSRF Protection"):
            await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_crawler_ssrf_protection_private_192(self, monkeypatch):
        """192.168.x.x（プライベート）に解決される場合も ValueError を投げること。"""
        monkeypatch.setattr(
            socket, "gethostbyname_ex", lambda host: (host, [], ["192.168.1.100"])
        )
        crawler = AgentPassCrawler()
        with pytest.raises(ValueError, match="SSRF Protection"):
            await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_crawler_ssrf_protection_dns_failure(self, monkeypatch):
        """DNS 解決失敗も ValueError を投げること（解決不能 = 安全でない）。"""
        def _raise(host):
            raise socket.gaierror("DNS lookup failed")
        monkeypatch.setattr(socket, "gethostbyname_ex", _raise)
        crawler = AgentPassCrawler()
        with pytest.raises(ValueError, match="SSRF Protection"):
            await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_ssrf_check_does_not_make_http_call(self, monkeypatch):
        """SSRF 拒否時は HTTP 通信を一切行わないこと。"""
        monkeypatch.setattr(
            socket, "gethostbyname_ex", lambda host: (host, [], ["127.0.0.1"])
        )
        crawler = AgentPassCrawler()
        async with respx.mock:
            route = respx.get(METADATA_URL).mock(return_value=httpx.Response(200))
            with pytest.raises(ValueError, match="SSRF Protection"):
                await crawler.fetch_merchant_metadata(BASE_DOMAIN)
            assert route.called is False     # HTTP 通信ゼロを確認

    async def test_ssrf_empty_ip_list(self, monkeypatch):
        """DNS が空の IP リストを返した場合も ValueError を投げること（line 130）。"""
        monkeypatch.setattr(
            socket, "gethostbyname_ex", lambda host: (host, [], [])  # 空リスト
        )
        crawler = AgentPassCrawler()
        with pytest.raises(ValueError, match="SSRF Protection"):
            await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_ssrf_unparseable_ip_string(self, monkeypatch):
        """ipaddress が解釈できない文字列を返した場合も ValueError を投げること（lines 144-145）。"""
        monkeypatch.setattr(
            socket, "gethostbyname_ex", lambda host: (host, [], ["not-an-ip-!!"])
        )
        crawler = AgentPassCrawler()
        with pytest.raises(ValueError, match="SSRF Protection"):
            await crawler.fetch_merchant_metadata(BASE_DOMAIN)


# ---------------------------------------------------------------------------
# 異常系 — 1MB ストリーム制限
# ---------------------------------------------------------------------------

class TestCrawlerMaxBytesExceeded:
    async def test_crawler_max_bytes_exceeded(self, monkeypatch):
        """
        指定バイト超過で即切断され、ValueError（"Security Boundary Exceeded"）を
        投げること（テスト用に max_bytes を極小に設定）。
        """
        _mock_public_dns(monkeypatch)
        small_limit = 10
        crawler = AgentPassCrawler(max_bytes=small_limit)
        oversized = b"x" * (small_limit + 1)

        async with respx.mock:
            respx.get(METADATA_URL).mock(
                return_value=httpx.Response(200, content=oversized)
            )
            with pytest.raises(ValueError, match="Security Boundary Exceeded"):
                await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_exactly_at_limit_is_accepted(self, monkeypatch):
        """max_bytes ちょうどは受け入れられること（`>` 比較のため境界値は通過）。"""
        _mock_public_dns(monkeypatch)
        payload = _valid_payload()
        exact_content = _json.dumps(payload).encode()
        crawler = AgentPassCrawler(max_bytes=len(exact_content))

        async with respx.mock:
            respx.get(METADATA_URL).mock(
                return_value=httpx.Response(200, content=exact_content)
            )
            result = await crawler.fetch_merchant_metadata(BASE_DOMAIN)

        assert isinstance(result, MerchantMetadata)


# ---------------------------------------------------------------------------
# 異常系 — HTTP エラー
# ---------------------------------------------------------------------------

class TestCrawlerHttpError:
    async def test_crawler_http_error_404(self, monkeypatch):
        """404 レスポンスは RuntimeError にラップされること。"""
        _mock_public_dns(monkeypatch)
        crawler = AgentPassCrawler()

        async with respx.mock:
            respx.get(METADATA_URL).mock(return_value=httpx.Response(404))
            with pytest.raises(RuntimeError):
                await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_crawler_http_error_500(self, monkeypatch):
        """500 レスポンスは RuntimeError にラップされること。"""
        _mock_public_dns(monkeypatch)
        crawler = AgentPassCrawler()

        async with respx.mock:
            respx.get(METADATA_URL).mock(return_value=httpx.Response(500))
            with pytest.raises(RuntimeError):
                await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_crawler_http_error_message_contains_status(self, monkeypatch):
        """RuntimeError のメッセージにステータスコードが含まれること。"""
        _mock_public_dns(monkeypatch)
        crawler = AgentPassCrawler()

        async with respx.mock:
            respx.get(METADATA_URL).mock(return_value=httpx.Response(403))
            with pytest.raises(RuntimeError, match="403"):
                await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_network_error_raises_runtime_error(self, monkeypatch):
        """ネットワーク接続エラーは RuntimeError（"Network error"）にラップされること（line 173）。"""
        _mock_public_dns(monkeypatch)
        crawler = AgentPassCrawler()

        async with respx.mock:
            respx.get(METADATA_URL).mock(side_effect=httpx.ConnectError("unreachable"))
            with pytest.raises(RuntimeError, match="Network error"):
                await crawler.fetch_merchant_metadata(BASE_DOMAIN)


# ---------------------------------------------------------------------------
# 異常系 — レスポンス内容不正
# ---------------------------------------------------------------------------

class TestCrawlerMalformedResponse:
    async def test_invalid_json_raises_value_error(self, monkeypatch):
        """不正な JSON バイト列は ValueError（"Invalid JSON"）を投げること（lines 182-183）。"""
        _mock_public_dns(monkeypatch)
        crawler = AgentPassCrawler()

        async with respx.mock:
            respx.get(METADATA_URL).mock(
                return_value=httpx.Response(200, content=b"this is not json {{{")
            )
            with pytest.raises(ValueError, match="Invalid JSON"):
                await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_json_array_raises_value_error(self, monkeypatch):
        """JSON が配列（オブジェクトでない）の場合も ValueError を投げること（line 186）。"""
        _mock_public_dns(monkeypatch)
        crawler = AgentPassCrawler()

        async with respx.mock:
            respx.get(METADATA_URL).mock(
                return_value=httpx.Response(200, json=[{"not": "an object"}])
            )
            with pytest.raises(ValueError, match="must be a JSON object"):
                await crawler.fetch_merchant_metadata(BASE_DOMAIN)

    async def test_schema_validation_failure_raises_value_error(self, monkeypatch):
        """必須フィールド欠如で Pydantic 検証が失敗した場合、ValueError（"Schema validation failed"）を
        投げること（lines 197-198）。"""
        _mock_public_dns(monkeypatch)
        crawler = AgentPassCrawler()

        async with respx.mock:
            respx.get(METADATA_URL).mock(
                return_value=httpx.Response(200, json={"agentpass_version": "1.0.0"})
            )
            with pytest.raises(ValueError, match="Schema validation failed"):
                await crawler.fetch_merchant_metadata(BASE_DOMAIN)
