"""
AgentPass Core — リプレイ攻撃検知（AnomalyDetector）

インメモリ辞書で使用済み JTI を管理し、同一 JTI の再送信を即座に検知する。
メモリ肥大化を防ぐため、メソッド呼び出し毎に有効期限切れエントリを GC する。
"""

from __future__ import annotations

import time
from collections.abc import Callable


class AnomalyDetector:
    """
    JWT の jti クレームに基づくリプレイ攻撃検知クラス。

    使い方:
      detector = AnomalyDetector()
      if detector.is_replay_attack(claims.token_id, claims.expires_at):
          return 403  # リプレイ攻撃

    _time_func を差し替えることで、テスト時に時刻を完全制御できる。
    """

    def __init__(self, _time_func: Callable[[], float] = time.time) -> None:
        self._used_jtis: dict[str, float] = {}  # jti → exp（unix timestamp）
        self._time_func = _time_func

    def is_replay_attack(self, jti: str, exp: float) -> bool:
        """
        JTI がリプレイ攻撃かどうかを判定する。

        Args:
            jti: JWT の jti クレーム（トークン一意識別子）
            exp: JWT の exp クレーム（有効期限 unix timestamp）

        Returns:
            True  — 既使用の JTI（リプレイ攻撃）
            False — 初回受信（辞書に登録して以降の再利用を検知可能にする）
        """
        now = self._time_func()

        # 簡易 GC: 有効期限切れのエントリをクリーンアップ
        self._used_jtis = {k: v for k, v in self._used_jtis.items() if v > now}

        if jti in self._used_jtis:
            return True

        self._used_jtis[jti] = exp
        return False
