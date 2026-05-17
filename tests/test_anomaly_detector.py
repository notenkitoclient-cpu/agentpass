"""
src/core/anomaly_detector.py のテスト

FakeTime で時刻を制御し、sleep なしで GC・リプレイ検知を検証する。
"""

from __future__ import annotations

import uuid

from core.anomaly_detector import AnomalyDetector


# ---------------------------------------------------------------------------
# テスト用タイムヘルパー
# ---------------------------------------------------------------------------

class FakeTime:
    def __init__(self, start: float) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


# ---------------------------------------------------------------------------
# 初回 JTI — False を返す
# ---------------------------------------------------------------------------

class TestFirstTimeJti:
    def test_new_jti_returns_false(self):
        detector = AnomalyDetector()
        result = detector.is_replay_attack(str(uuid.uuid4()), exp=9999999999.0)
        assert result is False

    def test_new_jti_is_stored_in_dict(self):
        ft = FakeTime(1000.0)
        detector = AnomalyDetector(_time_func=ft)
        jti = str(uuid.uuid4())
        detector.is_replay_attack(jti, exp=1060.0)
        assert jti in detector._used_jtis

    def test_stored_value_is_exp(self):
        ft = FakeTime(1000.0)
        detector = AnomalyDetector(_time_func=ft)
        jti = str(uuid.uuid4())
        detector.is_replay_attack(jti, exp=1060.0)
        assert detector._used_jtis[jti] == 1060.0

    def test_multiple_distinct_jtis_all_return_false(self):
        detector = AnomalyDetector()
        exp = 9999999999.0
        results = [detector.is_replay_attack(str(uuid.uuid4()), exp=exp) for _ in range(5)]
        assert all(r is False for r in results)


# ---------------------------------------------------------------------------
# 2回目の同一 JTI — True を返す（リプレイ攻撃）
# ---------------------------------------------------------------------------

class TestReplayDetection:
    def test_same_jti_second_call_returns_true(self):
        detector = AnomalyDetector()
        jti = str(uuid.uuid4())
        exp = 9999999999.0
        detector.is_replay_attack(jti, exp=exp)
        result = detector.is_replay_attack(jti, exp=exp)
        assert result is True

    def test_replay_detected_on_third_call_too(self):
        detector = AnomalyDetector()
        jti = str(uuid.uuid4())
        exp = 9999999999.0
        detector.is_replay_attack(jti, exp=exp)
        assert detector.is_replay_attack(jti, exp=exp) is True
        assert detector.is_replay_attack(jti, exp=exp) is True

    def test_different_jti_not_detected_as_replay(self):
        detector = AnomalyDetector()
        exp = 9999999999.0
        jti_a = str(uuid.uuid4())
        jti_b = str(uuid.uuid4())
        detector.is_replay_attack(jti_a, exp=exp)
        result = detector.is_replay_attack(jti_b, exp=exp)
        assert result is False


# ---------------------------------------------------------------------------
# GC — 有効期限切れ JTI のクリーンアップ
# ---------------------------------------------------------------------------

class TestGarbageCollection:
    def test_expired_jti_is_removed_after_gc(self):
        ft = FakeTime(1000.0)
        detector = AnomalyDetector(_time_func=ft)

        jti_old = str(uuid.uuid4())
        detector.is_replay_attack(jti_old, exp=1010.0)  # exp=1010, now=1000
        assert jti_old in detector._used_jtis

        ft.advance(20)  # now=1020 > exp=1010 → expired
        jti_new = str(uuid.uuid4())
        detector.is_replay_attack(jti_new, exp=1080.0)  # 新規 JTI が GC をトリガー

        assert jti_old not in detector._used_jtis
        assert jti_new in detector._used_jtis

    def test_non_expired_jti_survives_gc(self):
        ft = FakeTime(1000.0)
        detector = AnomalyDetector(_time_func=ft)

        jti_a = str(uuid.uuid4())
        jti_b = str(uuid.uuid4())
        detector.is_replay_attack(jti_a, exp=1050.0)  # expires at 1050
        detector.is_replay_attack(jti_b, exp=1100.0)  # expires at 1100

        ft.advance(60)  # now=1060: jti_a expired, jti_b alive

        jti_c = str(uuid.uuid4())
        detector.is_replay_attack(jti_c, exp=1120.0)  # GC triggered

        assert jti_a not in detector._used_jtis
        assert jti_b in detector._used_jtis
        assert jti_c in detector._used_jtis

    def test_gc_allows_reuse_of_expired_jti(self):
        """有効期限切れ JTI は GC 後に新規として扱われる（実運用では token_verifier が exp を弾く）。"""
        ft = FakeTime(1000.0)
        detector = AnomalyDetector(_time_func=ft)

        jti = str(uuid.uuid4())
        detector.is_replay_attack(jti, exp=1010.0)

        ft.advance(20)  # jti は expired

        # GC をトリガーする別の JTI を呼び出す
        detector.is_replay_attack(str(uuid.uuid4()), exp=1080.0)

        # 元の jti は GC されたので False（新規扱い）
        result = detector.is_replay_attack(jti, exp=1080.0)
        assert result is False

    def test_empty_dict_after_all_expired(self):
        ft = FakeTime(1000.0)
        detector = AnomalyDetector(_time_func=ft)

        for _ in range(3):
            detector.is_replay_attack(str(uuid.uuid4()), exp=1010.0)

        ft.advance(20)
        detector.is_replay_attack(str(uuid.uuid4()), exp=1080.0)

        # 初期 3件はすべて削除されて 1件だけ残る
        assert len(detector._used_jtis) == 1
