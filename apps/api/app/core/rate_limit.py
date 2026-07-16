"""Rate limiter em memória (sliding window) para SP-02.

Single-instance por design (MVP). Se um dia migrar para múltiplas réplicas,
trocar por Redis. Duas janelas independentes:

- IP: 5 tentativas/min (qualquer /auth/login, inclusive as bem-sucedidas).
- Email: 10 FALHAS em 15 min (só incrementa em senha errada / usuário inexistente).
"""

from __future__ import annotations

import time
from threading import Lock

from app.core.config import get_settings


class SlidingWindowCounter:
    def __init__(self, window_seconds: int, max_events: int) -> None:
        self.window_seconds = window_seconds
        self.max_events = max_events
        self._events: dict[str, list[float]] = {}
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        events = [t for t in self._events.get(key, []) if t > cutoff]
        self._events[key] = events
        return events

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            events = self._prune(key, time.monotonic())
            return len(events) >= self.max_events

    def record(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            events = self._prune(key, now)
            events.append(now)
            self._events[key] = events

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


_ip_limiter: SlidingWindowCounter | None = None
_email_fail_limiter: SlidingWindowCounter | None = None


def get_ip_limiter() -> SlidingWindowCounter:
    global _ip_limiter
    if _ip_limiter is None:
        settings = get_settings()
        _ip_limiter = SlidingWindowCounter(
            window_seconds=60, max_events=settings.rate_limit_login_per_min
        )
    return _ip_limiter


def get_email_fail_limiter() -> SlidingWindowCounter:
    global _email_fail_limiter
    if _email_fail_limiter is None:
        _email_fail_limiter = SlidingWindowCounter(window_seconds=15 * 60, max_events=10)
    return _email_fail_limiter


def reset_login_limiters() -> None:
    """Usado por testes para isolar o estado entre casos."""
    if _ip_limiter is not None:
        _ip_limiter.reset()
    if _email_fail_limiter is not None:
        _email_fail_limiter.reset()
