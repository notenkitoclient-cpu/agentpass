"""
AgentPass Identity — M2M 自律信用スコアリング

過去の振る舞い（成功回数・エラーレート・予算超過）に基づく動的スコア計算。
スコアは 0.0 〜 100.0 の範囲にクリップされる。

計算式:
  基本スコア = 100.0 + (age_days * 0.1) + (success_count * 0.01)
  エラーペナルティ乗数     = max(0.1, 1.0 - (error_rate * 0.5))
  予算超過ペナルティ乗数   = max(0.1, 1.0 - (budget_overflow_count * 0.2))
  最終スコア = clip(基本スコア × 両乗数, 0.0, 100.0)
"""

from __future__ import annotations


class CreditScorer:
    """エージェントの信用スコアを計算するスコアラー。"""

    def calculate_score(
        self,
        age_days: int,
        success_count: int,
        error_rate: float,
        budget_overflow_count: int,
    ) -> float:
        """
        信用スコアを計算して返す。

        Args:
            age_days: アカウント年齢（日数）
            success_count: 成功した取引の累計件数
            error_rate: エラー率（0.0〜1.0）
            budget_overflow_count: 予算超過の累計回数

        Returns:
            0.0 〜 100.0 にクリップされた信用スコア
        """
        base = 100.0 + (age_days * 0.1) + (success_count * 0.01)
        error_multiplier = max(0.1, 1.0 - (error_rate * 0.5))
        budget_multiplier = max(0.1, 1.0 - (budget_overflow_count * 0.2))
        score = base * error_multiplier * budget_multiplier
        return max(0.0, min(100.0, score))
