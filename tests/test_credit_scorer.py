"""
src/identity/credit_scorer.py のテスト

CreditScorer.calculate_score() のロジックを網羅的に検証する。

計算式:
  基本スコア = 100.0 + (age_days * 0.1) + (success_count * 0.01)
  エラーペナルティ乗数   = max(0.1, 1.0 - (error_rate * 0.5))
  予算超過ペナルティ乗数 = max(0.1, 1.0 - (budget_overflow_count * 0.2))
  最終スコア = clip(基本スコア × 両乗数, 0.0, 100.0)
"""

from __future__ import annotations

import pytest

from src.identity.credit_scorer import CreditScorer


# ---------------------------------------------------------------------------
# クリーンな状態（ペナルティなし）
# ---------------------------------------------------------------------------

class TestCleanState:
    def setup_method(self):
        self.scorer = CreditScorer()

    def test_all_zero_inputs_returns_100(self):
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=0.0, budget_overflow_count=0
        )
        assert score == 100.0

    def test_age_bonus_visible_with_error_penalty(self):
        # base = 100 + 10*0.1 = 101, error_multiplier = 0.5 → 101 * 0.5 = 50.5
        score = self.scorer.calculate_score(
            age_days=10, success_count=0, error_rate=1.0, budget_overflow_count=0
        )
        assert abs(score - 50.5) < 1e-9

    def test_success_bonus_visible_with_error_penalty(self):
        # base = 100 + 100*0.01 = 101, error_multiplier = 0.5 → 50.5
        score = self.scorer.calculate_score(
            age_days=0, success_count=100, error_rate=1.0, budget_overflow_count=0
        )
        assert abs(score - 50.5) < 1e-9

    def test_returns_float(self):
        score = self.scorer.calculate_score(
            age_days=1, success_count=1, error_rate=0.1, budget_overflow_count=0
        )
        assert isinstance(score, float)


# ---------------------------------------------------------------------------
# エラーペナルティ乗数
# ---------------------------------------------------------------------------

class TestErrorPenalty:
    def setup_method(self):
        self.scorer = CreditScorer()

    def test_zero_error_rate_no_penalty(self):
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=0.0, budget_overflow_count=0
        )
        assert score == 100.0

    def test_50_percent_error_rate_gives_75_percent_multiplier(self):
        # multiplier = 1.0 - (0.5 * 0.5) = 0.75
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=0.5, budget_overflow_count=0
        )
        assert abs(score - 75.0) < 1e-9

    def test_100_percent_error_rate_gives_50_percent_multiplier(self):
        # multiplier = 1.0 - (1.0 * 0.5) = 0.5
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=1.0, budget_overflow_count=0
        )
        assert abs(score - 50.0) < 1e-9

    def test_extreme_error_rate_floors_multiplier_at_0_1(self):
        # error_rate=3.0 → 1.0 - 1.5 = -0.5 → max(0.1, -0.5) = 0.1
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=3.0, budget_overflow_count=0
        )
        assert abs(score - 10.0) < 1e-9

    def test_error_rate_2_floors_multiplier_at_0_1(self):
        # error_rate=2.0 → 1.0 - 1.0 = 0.0 → max(0.1, 0.0) = 0.1
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=2.0, budget_overflow_count=0
        )
        assert abs(score - 10.0) < 1e-9


# ---------------------------------------------------------------------------
# 予算超過ペナルティ乗数
# ---------------------------------------------------------------------------

class TestBudgetOverflowPenalty:
    def setup_method(self):
        self.scorer = CreditScorer()

    def test_zero_overflow_no_penalty(self):
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=0.0, budget_overflow_count=0
        )
        assert score == 100.0

    def test_one_overflow_gives_80_percent_multiplier(self):
        # multiplier = 1.0 - (1 * 0.2) = 0.8
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=0.0, budget_overflow_count=1
        )
        assert abs(score - 80.0) < 1e-9

    def test_three_overflows_gives_40_percent_multiplier(self):
        # multiplier = 1.0 - (3 * 0.2) = 0.4
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=0.0, budget_overflow_count=3
        )
        assert abs(score - 40.0) < 1e-9

    def test_four_overflows_gives_20_percent_multiplier(self):
        # multiplier = 1.0 - (4 * 0.2) = 0.2
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=0.0, budget_overflow_count=4
        )
        assert abs(score - 20.0) < 1e-9

    def test_five_overflows_floors_multiplier_at_0_1(self):
        # multiplier = max(0.1, 1.0 - 5*0.2) = max(0.1, 0.0) = 0.1
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=0.0, budget_overflow_count=5
        )
        assert abs(score - 10.0) < 1e-9

    def test_extreme_overflow_count_floors_at_0_1(self):
        # multiplier = max(0.1, 1.0 - 100*0.2) = 0.1
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=0.0, budget_overflow_count=100
        )
        assert abs(score - 10.0) < 1e-9


# ---------------------------------------------------------------------------
# 上限・下限クリップ処理
# ---------------------------------------------------------------------------

class TestClipping:
    def setup_method(self):
        self.scorer = CreditScorer()

    def test_large_age_clips_to_100(self):
        # base = 100 + 10000*0.1 = 1100, no penalty → clipped to 100.0
        score = self.scorer.calculate_score(
            age_days=10000, success_count=0, error_rate=0.0, budget_overflow_count=0
        )
        assert score == 100.0

    def test_large_success_count_clips_to_100(self):
        # base = 100 + 1000000*0.01 = 10100 → clipped to 100.0
        score = self.scorer.calculate_score(
            age_days=0, success_count=1000000, error_rate=0.0, budget_overflow_count=0
        )
        assert score == 100.0

    def test_extreme_bad_state_never_below_zero(self):
        # Both multipliers = 0.1: 100 * 0.1 * 0.1 = 1.0 (still > 0)
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=100.0, budget_overflow_count=100
        )
        assert score >= 0.0

    def test_both_floors_give_minimum_of_1(self):
        # base=100, both multipliers floored at 0.1 → 100 * 0.1 * 0.1 = 1.0
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=100.0, budget_overflow_count=100
        )
        assert abs(score - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# 複合ペナルティ
# ---------------------------------------------------------------------------

class TestCombinedPenalties:
    def setup_method(self):
        self.scorer = CreditScorer()

    def test_error_and_overflow_combined(self):
        # error_multiplier = max(0.1, 1 - 0.5*0.5) = 0.75
        # budget_multiplier = max(0.1, 1 - 2*0.2) = 0.6
        # score = 100.0 * 0.75 * 0.6 = 45.0
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=0.5, budget_overflow_count=2
        )
        assert abs(score - 45.0) < 1e-9

    def test_both_at_floor_gives_1(self):
        # Both multipliers = 0.1 → 100 * 0.1 * 0.1 = 1.0
        score = self.scorer.calculate_score(
            age_days=0, success_count=0, error_rate=10.0, budget_overflow_count=10
        )
        assert abs(score - 1.0) < 1e-9

    def test_age_success_and_combined_penalties(self):
        # base = 100 + 10*0.1 + 100*0.01 = 102.0
        # error_multiplier = max(0.1, 1 - 1.0*0.5) = 0.5
        # budget_multiplier = max(0.1, 1 - 1*0.2) = 0.8
        # score = 102.0 * 0.5 * 0.8 = 40.8
        score = self.scorer.calculate_score(
            age_days=10, success_count=100, error_rate=1.0, budget_overflow_count=1
        )
        assert abs(score - 40.8) < 1e-9
