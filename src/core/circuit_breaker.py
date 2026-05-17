"""
AgentPass Core — サーキットブレーカー（安全弁）

ai-instructions.md セクション3 に準拠。
agent_id ごとに1分間のスライディングウィンドウで
「累積消費額」と「累積リクエスト数」を追跡する。

スレッドセーフ：複数スレッドから同時呼び出し可能。
時刻注入対応：テストでは _time_func に差し替えることで
              sleep なしで時間経過をシミュレートできる。
"""

import threading
import time
from dataclasses import dataclass

WINDOW_SECONDS = 60


# ---------------------------------------------------------------------------
# 例外クラス（ai-instructions.md セクション7 に対応）
# ---------------------------------------------------------------------------

class CircuitBreakerError(Exception):
    """サーキットブレーカー起動の基底例外。http_status と error_code を持つ。"""
    http_status: int
    error_code: str


class BudgetExceededError(CircuitBreakerError):
    """429 BUDGET_EXCEEDED — 1分間の予算上限を超過"""
    http_status = 429
    error_code = "BUDGET_EXCEEDED"


class RateLimitedError(CircuitBreakerError):
    """429 RATE_LIMITED — 1分間のリクエスト数上限を超過"""
    http_status = 429
    error_code = "RATE_LIMITED"


# ---------------------------------------------------------------------------
# 状態の返却型（ai-instructions.md セクション2.2 の circuit_breaker オブジェクト）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CircuitBreakerStatus:
    budget_remaining_1min: float    # JPY
    requests_remaining_1min: int


# ---------------------------------------------------------------------------
# サーキットブレーカー本体
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    agent_id ごとにスライディングウィンドウで使用量を管理する。

    デフォルト制限（ai-instructions.md セクション3）:
      - 1分間の最大消費額: 0.10 JPY
      - 1分間の最大リクエスト数: 100
      - 1トランザクションの上限: 10.00 JPY
    """

    def __init__(
        self,
        max_budget_per_minute: float = 0.10,
        max_requests_per_minute: int = 100,
        max_single_transaction: float = 10.00,
        _time_func=time.time,
    ):
        self._max_budget = max_budget_per_minute
        self._max_requests = max_requests_per_minute
        self._max_single = max_single_transaction
        self._time_func = _time_func
        # { agent_id: [(timestamp, amount), ...] }
        self._windows: dict[str, list[tuple[float, float]]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 公開インターフェース
    # ------------------------------------------------------------------

    def check_and_record(
        self, agent_id: str, amount: float
    ) -> CircuitBreakerStatus:
        """
        制限チェック + 使用量の記録を原子的に行う。

        通過した場合のみ使用量を記録し、更新後の残高を返す。
        制限超過の場合は例外を送出し、使用量は記録しない。

        チェック順序:
          1. 単一トランザクション上限（BudgetExceededError）
          2. 累積予算上限（BudgetExceededError）
          3. 累積リクエスト数上限（RateLimitedError）
        """
        with self._lock:
            now = self._time_func()
            window = self._prune(agent_id, now)

            current_spend = sum(amt for _, amt in window)
            current_requests = len(window)

            # 1. 単一トランザクション上限
            if amount > self._max_single:
                raise BudgetExceededError(
                    f"Single transaction amount {amount:.4f} JPY exceeds "
                    f"max_single_transaction limit {self._max_single:.2f} JPY"
                )

            # 2. 累積予算上限（予算チェックをレートより優先）
            if current_spend + amount > self._max_budget:
                remaining = max(0.0, self._max_budget - current_spend)
                raise BudgetExceededError(
                    f"Cumulative spend {current_spend + amount:.4f} JPY would exceed "
                    f"{self._max_budget:.2f} JPY/min limit. "
                    f"Remaining: {remaining:.4f} JPY"
                )

            # 3. 累積リクエスト数上限
            if current_requests + 1 > self._max_requests:
                raise RateLimitedError(
                    f"Request count {current_requests + 1} would exceed "
                    f"{self._max_requests} requests/min limit"
                )

            # 全チェック通過 → 記録
            self._windows[agent_id].append((now, amount))

            return CircuitBreakerStatus(
                budget_remaining_1min=round(
                    self._max_budget - current_spend - amount, 6
                ),
                requests_remaining_1min=self._max_requests - current_requests - 1,
            )

    def get_status(self, agent_id: str) -> CircuitBreakerStatus:
        """現在の残高を参照する（使用量は記録しない）。"""
        with self._lock:
            now = self._time_func()
            window = self._prune(agent_id, now)
            current_spend = sum(amt for _, amt in window)
            current_requests = len(window)
            return CircuitBreakerStatus(
                budget_remaining_1min=round(
                    max(0.0, self._max_budget - current_spend), 6
                ),
                requests_remaining_1min=max(0, self._max_requests - current_requests),
            )

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _prune(
        self, agent_id: str, now: float
    ) -> list[tuple[float, float]]:
        """60秒より古いエントリをウィンドウから除去して返す。"""
        cutoff = now - WINDOW_SECONDS
        window = [
            entry for entry in self._windows.get(agent_id, [])
            if entry[0] > cutoff
        ]
        self._windows[agent_id] = window
        return window
