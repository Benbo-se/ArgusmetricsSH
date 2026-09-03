"""Rate limiting for the endpoints that abuse targets.

Used for:
- /track endpoints (DoS / analytics poisoning prevention)
- Authentication: login, signup, verification, password reset
- Dashboard password verification (brute-force prevention)

**The counters live in this process.** With one worker that is correct and
needs nothing else. With several, each worker keeps its own counts, so every
limit is effectively multiplied by the worker count, and a restart forgets
everything.

That is a deployment question rather than a code one, so the code does not
assume the answer: `get_rate_limiter()` picks the backend from configuration,
and anything implementing `is_rate_limited` and `reset` can be dropped in. A
shared backend, Redis being the obvious one, becomes a config value rather
than a refactor. Deliberately not written yet: an untested implementation of
a security control is worse than a missing one, and RATE_LIMIT_BACKEND
refuses anything it does not actually have.
"""
import time
import threading
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    In-memory rate limiter using sliding window counters per key.

    Thread-safe. Automatically cleans up expired entries to prevent
    memory growth. No external dependencies (no Redis needed).
    """

    # Hard cap on tracked keys: keys are attacker-controlled strings (emails,
    # IPs), so an unbounded map is a memory-exhaustion vector.
    MAX_KEYS = 50_000

    def __init__(self):
        # key -> (window_seconds, [timestamps])
        self._windows: dict[str, tuple[int, list[float]]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 300  # Clean up every 5 minutes

    def is_rate_limited(self, key: str, limit: int, window_seconds: int) -> bool:
        """
        Check if a key has exceeded its rate limit.

        Args:
            key: Identifier (e.g. IP address, or "pwd:{ip}:{token}")
            limit: Maximum requests allowed in the window
            window_seconds: Time window in seconds

        Returns:
            True if rate limited (request should be rejected)
        """
        now = time.monotonic()

        with self._lock:
            # Periodic cleanup of stale entries
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup(now)
                self._last_cleanup = now

            # Get or create request timestamps for this key
            if key not in self._windows:
                self._windows[key] = (window_seconds, [])

            _, timestamps = self._windows[key]

            # Remove timestamps outside the current window
            cutoff = now - window_seconds
            timestamps = [t for t in timestamps if t > cutoff]
            self._windows[key] = (window_seconds, timestamps)

            # Check if limit exceeded
            if len(timestamps) >= limit:
                return True

            # Record this request
            timestamps.append(now)
            return False

    def reset(self) -> None:
        """Forget every counter.

        For tests, which share one client address and would otherwise throttle
        each other. Part of the interface rather than test code reaching into
        _windows, so a different backend can honour it too.
        """
        with self._lock:
            self._windows.clear()
            self._last_cleanup = time.monotonic()

    def _cleanup(self, now: float) -> None:
        """Remove expired entries. Each key is judged against ITS OWN window —
        judging every key by the caller's window let high-frequency short-window
        traffic (/track, 60s) wipe hour-long login/reset/resend counters every
        5 minutes, gutting those limits."""
        expired_keys = [
            key for key, (window, timestamps) in self._windows.items()
            if not timestamps or timestamps[-1] < now - window
        ]
        for key in expired_keys:
            del self._windows[key]

        # Bounded map: if still over cap after expiry, evict the oldest keys
        if len(self._windows) > self.MAX_KEYS:
            overflow = len(self._windows) - self.MAX_KEYS
            oldest = sorted(self._windows.items(), key=lambda kv: kv[1][1][-1] if kv[1][1] else 0.0)
            for key, _ in oldest[:overflow]:
                del self._windows[key]
            logger.warning(f"Rate limiter over MAX_KEYS: evicted {overflow} oldest keys")

        if expired_keys:
            logger.debug(f"Rate limiter cleanup: removed {len(expired_keys)} expired keys")


def get_rate_limiter():
    """The limiter this deployment uses.

    A backend needs two methods: is_rate_limited(key, limit, window_seconds)
    returning True when the request should be refused, and reset().
    """
    from app.config import settings

    backend = getattr(settings, "RATE_LIMIT_BACKEND", "memory")

    if backend == "memory":
        return RateLimiter()

    # Louder than silently falling back: a deployment that asked for a shared
    # limiter and got a per-process one would believe it had a limit it does
    # not have, across every worker.
    raise ValueError(
        f"RATE_LIMIT_BACKEND={backend!r} is not implemented. Only 'memory' "
        "exists today, which counts per process and so multiplies every limit "
        "by the number of workers. Implement the backend before configuring it."
    )


# Singleton instance shared across the application
rate_limiter = get_rate_limiter()
