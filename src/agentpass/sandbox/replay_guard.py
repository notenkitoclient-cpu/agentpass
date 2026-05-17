"""
EXP-005b: Thread-safe JTI replay guard.

Atomically checks and registers JTIs to prevent double-spending
under concurrent requests. All state is in-memory (sandbox only).
"""

from __future__ import annotations

import threading


class ReplayGuard:
    """
    Atomic JTI check-and-register.

    check_and_register() is the only public method.
    It returns True (first occurrence — approved) or False (replay).
    The check + register is a single critical section, so two concurrent
    calls with the same JTI cannot both return True.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def check_and_register(self, jti: str) -> bool:
        """
        Return True if jti is seen for the first time (token approved).
        Return False if jti was already registered (replay detected).
        The operation is atomic: concurrent calls are serialized.
        """
        with self._lock:
            if jti in self._seen:
                return False
            self._seen.add(jti)
            return True
