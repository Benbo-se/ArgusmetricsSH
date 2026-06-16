"""
In-memory rate limiter for protecting endpoints against abuse.

Used for:
- /track endpoints (DoS / analytics poisoning prevention)
- Dashboard password verification (brute-force prevention)
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

    def __init__(self):
        self._windows: dict[str, list[float]] = {}
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
                self._cleanup(now, window_seconds)
                self._last_cleanup = now

            # Get or create request timestamps for this key
            if key not in self._windows:
                self._windows[key] = []

            timestamps = self._windows[key]

            # Remove timestamps outside the current window
            cutoff = now - window_seconds
            self._windows[key] = [t for t in timestamps if t > cutoff]
            timestamps = self._windows[key]

            # Check if limit exceeded
            if len(timestamps) >= limit:
                return True

            # Record this request
            timestamps.append(now)
            return False

    def _cleanup(self, now: float, default_window: int) -> None:
        """Remove all expired entries to prevent memory growth."""
        cutoff = now - default_window
        expired_keys = [
            key for key, timestamps in self._windows.items()
            if not timestamps or timestamps[-1] < cutoff
        ]
        for key in expired_keys:
            del self._windows[key]

        if expired_keys:
            logger.debug(f"Rate limiter cleanup: removed {len(expired_keys)} expired keys")


# Singleton instance shared across the application
rate_limiter = RateLimiter()
