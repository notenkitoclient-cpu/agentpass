"""
circuit_breaker の動作確認テスト

時刻注入（FakeTime）を使うことで sleep なしで
スライディングウィンドウの時間経過を再現する。
"""

import pytest

from src.core.circuit_breaker import (
    BudgetExceededError,
    CircuitBreaker,
    CircuitBreakerStatus,
    RateLimitedError,
)
from src.core.token_issuer import TokenRequest, generate_keypair, issue_token


# ---------------------------------------------------------------------------
# テスト用ユーティリティ
# ---------------------------------------------------------------------------

class FakeTime:
    """制御可能な時刻ソース。CircuitBreaker の _time_func に注入して使う。"""

    def __init__(self, start: float = 1_000.0):
        self.current = start

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def make_cb(
    max_budget: float = 0.10,
    max_requests: int = 100,
    max_single: float = 10.00,
    fake_time: FakeTime | None = None,
) -> CircuitBreaker:
    kwargs = dict(
        max_budget_per_minute=max_budget,
        max_requests_per_minute=max_requests,
        max_single_transaction=max_single,
    )
    if fake_time is not None:
        kwargs["_time_func"] = fake_time
    return CircuitBreaker(**kwargs)


# ---------------------------------------------------------------------------
# 正常系
# ---------------------------------------------------------------------------

class TestNormalCase:
    def test_first_request_returns_full_remaining(self):
        cb = make_cb(max_budget=0.10, max_requests=100)
        status = cb.check_and_record("agent-a", 0.01)

        assert isinstance(status, CircuitBreakerStatus)
        assert abs(status.budget_remaining_1min - 0.09) < 1e-6
        assert status.requests_remaining_1min == 99

    def test_remaining_decreases_with_each_request(self):
        cb = make_cb()
        cb.check_and_record("agent-a", 0.01)
        cb.check_and_record("agent-a", 0.02)
        status = cb.check_and_record("agent-a", 0.03)

        assert abs(status.budget_remaining_1min - 0.04) < 1e-6
        assert status.requests_remaining_1min == 97

    def test_different_agents_are_independent(self):
        cb = make_cb()
        cb.check_and_record("agent-a", 0.05)
        status_b = cb.check_and_record("agent-b", 0.03)

        # agent-b は agent-a の使用量を引き継がない
        assert abs(status_b.budget_remaining_1min - 0.07) < 1e-6
        assert status_b.requests_remaining_1min == 99

    def test_get_status_new_agent_has_full_budget(self):
        cb = make_cb(max_budget=0.10, max_requests=100)
        status = cb.get_status("brand-new-agent")

        assert abs(status.budget_remaining_1min - 0.10) < 1e-6
        assert status.requests_remaining_1min == 100

    def test_get_status_reflects_recorded_usage(self):
        cb = make_cb()
        cb.check_and_record("agent-a", 0.04)
        status = cb.get_status("agent-a")

        assert abs(status.budget_remaining_1min - 0.06) < 1e-6
        assert status.requests_remaining_1min == 99

    def test_exactly_at_budget_limit_passes(self):
        cb = make_cb(max_budget=0.10)
        cb.check_and_record("agent-a", 0.05)
        # 残り 0.05 ぴったり消費する → 通過するべき
        status = cb.check_and_record("agent-a", 0.05)

        assert abs(status.budget_remaining_1min - 0.0) < 1e-6


# ---------------------------------------------------------------------------
# 異常系 — 429 BUDGET_EXCEEDED
# ---------------------------------------------------------------------------

class TestBudgetExceeded:
    def test_single_request_over_limit_raises(self):
        cb = make_cb(max_budget=0.10)

        with pytest.raises(BudgetExceededError) as exc_info:
            cb.check_and_record("agent-a", 0.11)

        assert exc_info.value.http_status == 429
        assert exc_info.value.error_code == "BUDGET_EXCEEDED"

    def test_accumulated_spend_over_limit_raises(self):
        cb = make_cb(max_budget=0.10)
        cb.check_and_record("agent-a", 0.09)

        with pytest.raises(BudgetExceededError):
            cb.check_and_record("agent-a", 0.02)   # 合計 0.11 → 超過

    def test_failed_request_does_not_consume_budget(self):
        cb = make_cb(max_budget=0.10)
        cb.check_and_record("agent-a", 0.09)

        # 超過リクエストは弾かれる
        with pytest.raises(BudgetExceededError):
            cb.check_and_record("agent-a", 0.02)

        # 弾かれた後、残高はそのまま（0.09 消費済み）
        status = cb.get_status("agent-a")
        assert abs(status.budget_remaining_1min - 0.01) < 1e-6

    def test_single_transaction_over_max_raises(self):
        """単一トランザクション上限（10 JPY）の超過チェック。"""
        cb = make_cb(max_single=10.00)

        with pytest.raises(BudgetExceededError) as exc_info:
            cb.check_and_record("agent-a", 10.01)

        assert "max_single_transaction" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 異常系 — 429 RATE_LIMITED
# ---------------------------------------------------------------------------

class TestRateLimited:
    def test_over_request_limit_raises(self):
        cb = make_cb(max_budget=9999.0, max_requests=3)
        cb.check_and_record("agent-a", 0.001)
        cb.check_and_record("agent-a", 0.001)
        cb.check_and_record("agent-a", 0.001)

        with pytest.raises(RateLimitedError) as exc_info:
            cb.check_and_record("agent-a", 0.001)   # 4回目

        assert exc_info.value.http_status == 429
        assert exc_info.value.error_code == "RATE_LIMITED"

    def test_failed_request_does_not_count_toward_limit(self):
        cb = make_cb(max_budget=9999.0, max_requests=2)
        cb.check_and_record("agent-a", 0.001)
        cb.check_and_record("agent-a", 0.001)

        with pytest.raises(RateLimitedError):
            cb.check_and_record("agent-a", 0.001)   # 弾かれる

        # 弾かれた後の残カウントは 0（記録されていない）
        status = cb.get_status("agent-a")
        assert status.requests_remaining_1min == 0

    def test_exactly_at_request_limit_passes(self):
        cb = make_cb(max_budget=9999.0, max_requests=3)
        cb.check_and_record("agent-a", 0.001)
        cb.check_and_record("agent-a", 0.001)
        status = cb.check_and_record("agent-a", 0.001)   # ちょうど3回目

        assert status.requests_remaining_1min == 0


# ---------------------------------------------------------------------------
# スライディングウィンドウ（時刻注入による時間経過テスト）
# ---------------------------------------------------------------------------

class TestSlidingWindow:
    def test_entries_expire_after_60_seconds(self):
        ft = FakeTime(start=1000.0)
        cb = make_cb(max_budget=0.10, fake_time=ft)

        cb.check_and_record("agent-a", 0.09)   # t=1000

        ft.advance(61)                           # 61秒後 → ウィンドウ外

        # 古いエントリが消えているので、残高がリセットされている
        status = cb.get_status("agent-a")
        assert abs(status.budget_remaining_1min - 0.10) < 1e-6

    def test_partial_expiry_keeps_recent_entries(self):
        ft = FakeTime(start=1000.0)
        cb = make_cb(max_budget=0.10, fake_time=ft)

        cb.check_and_record("agent-a", 0.04)   # t=1000（古い）
        ft.advance(30)
        cb.check_and_record("agent-a", 0.03)   # t=1030（新しい）
        ft.advance(31)                           # t=1061: 最初の0.04は期限切れ

        # 0.03 のみ残っているはず
        status = cb.get_status("agent-a")
        assert abs(status.budget_remaining_1min - 0.07) < 1e-6

    def test_expired_budget_allows_new_requests(self):
        ft = FakeTime(start=1000.0)
        cb = make_cb(max_budget=0.10, fake_time=ft)

        # ウィンドウを満杯にする
        cb.check_and_record("agent-a", 0.10)

        ft.advance(61)   # ウィンドウ外へ

        # 新しいウィンドウではフル予算が使える
        status = cb.check_and_record("agent-a", 0.10)
        assert abs(status.budget_remaining_1min - 0.0) < 1e-6


# ---------------------------------------------------------------------------
# エラー優先順位
# ---------------------------------------------------------------------------

class TestErrorPriority:
    def test_budget_exceeded_takes_priority_over_rate_limited(self):
        """予算超過とリクエスト数超過が同時に発生する場合、予算超過を優先する。"""
        cb = make_cb(max_budget=0.001, max_requests=1)

        cb.check_and_record("agent-a", 0.001)   # 予算使い切り、かつ1回使用済み

        # 次のリクエストは「予算超過」かつ「回数超過」の両方に引っかかる
        with pytest.raises(BudgetExceededError):
            cb.check_and_record("agent-a", 0.001)


# ---------------------------------------------------------------------------
# token_issuer.py との統合テスト
# ---------------------------------------------------------------------------

class TestIntegrationWithIssueToken:
    @pytest.fixture
    def keypair(self):
        return generate_keypair()

    def _make_request(self, amount: float = 0.001) -> TokenRequest:
        return TokenRequest(
            agent_id="agent-xyz",
            destination_url="https://api.example.com/data",
            amount_requested=amount,
            purpose="test",
        )

    def test_issue_token_without_circuit_breaker_still_works(self, keypair):
        """後方互換性: circuit_breaker なしでも動作する。"""
        private_key, _ = keypair
        result = issue_token(self._make_request(), private_key)

        assert result.circuit_breaker is None

    def test_issue_token_records_usage_in_circuit_breaker(self, keypair):
        private_key, _ = keypair
        cb = make_cb()

        issue_token(self._make_request(0.02), private_key, cb)

        status = cb.get_status("agent-xyz")
        assert abs(status.budget_remaining_1min - 0.08) < 1e-6
        assert status.requests_remaining_1min == 99

    def test_issued_token_contains_circuit_breaker_status(self, keypair):
        private_key, _ = keypair
        cb = make_cb()

        result = issue_token(self._make_request(0.03), private_key, cb)

        assert result.circuit_breaker is not None
        assert abs(result.circuit_breaker.budget_remaining_1min - 0.07) < 1e-6
        assert result.circuit_breaker.requests_remaining_1min == 99

    def test_issue_token_raises_on_budget_exceeded_and_does_not_issue(self, keypair):
        private_key, _ = keypair
        cb = make_cb(max_budget=0.10)

        issue_token(self._make_request(0.09), private_key, cb)

        with pytest.raises(BudgetExceededError):
            # 合計 0.11 → 発行されない
            issue_token(self._make_request(0.02), private_key, cb)

        # 失敗後の使用量は 0.09 のまま
        status = cb.get_status("agent-xyz")
        assert abs(status.budget_remaining_1min - 0.01) < 1e-6

    def test_multiple_agents_tracked_independently_through_issue_token(self, keypair):
        private_key, _ = keypair
        cb = make_cb()

        req_a = TokenRequest(
            agent_id="agent-a",
            destination_url="https://api.example.com/data",
            amount_requested=0.05,
            purpose="test",
        )
        req_b = TokenRequest(
            agent_id="agent-b",
            destination_url="https://api.example.com/data",
            amount_requested=0.03,
            purpose="test",
        )

        result_a = issue_token(req_a, private_key, cb)
        result_b = issue_token(req_b, private_key, cb)

        assert abs(result_a.circuit_breaker.budget_remaining_1min - 0.05) < 1e-6
        assert abs(result_b.circuit_breaker.budget_remaining_1min - 0.07) < 1e-6
