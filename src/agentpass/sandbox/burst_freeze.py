"""
EXP-006: Sliding-window replay burst detector with temporary freeze.

Responsibilities (bounded):
  - Count replay_detected events within a time window
  - Trigger a temporary freeze when count >= threshold
  - Report whether freeze is currently active

Does NOT: modify audit log, raise exceptions, or call other sandbox components.
Callers (FreezeLayer) handle audit logging and exception propagation.
"""

from __future__ import annotations

import threading
import time


class BurstFreezeDetector:
    """
    Sliding-window counter that triggers a temporary freeze on replay bursts.

    All timestamps are injectable (``now`` parameter) for deterministic testing.
    When ``now`` is None the real ``time.monotonic()`` is used.

    Args:
        threshold:       Number of replays in ``window_seconds`` that trigger a freeze.
        window_seconds:  Sliding window length in seconds.
        freeze_seconds:  How long the freeze lasts after it is triggered.
    """

    def __init__(
        self,
        threshold: int,
        window_seconds: float,
        freeze_seconds: float = 30.0,
    ) -> None:
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self._threshold = threshold
        self._window = window_seconds
        self._freeze_seconds = freeze_seconds
        self._timestamps: list[float] = []
        self._frozen_until: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_replay(self, now: float | None = None) -> bool:
        """
        Record one replay event at time ``now``.

        Prunes events outside the sliding window, then checks whether the
        count meets or exceeds the threshold.

        Returns:
            True  — freeze was triggered by this call (count just hit threshold).
            False — freeze was NOT newly triggered (either already frozen, or
                    count still below threshold).
        """
        _now = now if now is not None else time.monotonic()
        with self._lock:
            self._timestamps.append(_now)
            self._prune(_now)
            if len(self._timestamps) >= self._threshold and _now >= self._frozen_until:
                self._frozen_until = _now + self._freeze_seconds
                return True
        return False

    def is_frozen(self, now: float | None = None) -> bool:
        """Return True if spending is currently frozen."""
        _now = now if now is not None else time.monotonic()
        with self._lock:
            return _now < self._frozen_until

    def replay_count_in_window(self, now: float | None = None) -> int:
        """Return the number of replay events recorded within the current window."""
        _now = now if now is not None else time.monotonic()
        with self._lock:
            self._prune(_now)
            return len(self._timestamps)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        self._timestamps = [t for t in self._timestamps if t >= cutoff]
