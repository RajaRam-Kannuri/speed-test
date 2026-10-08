"""Fixed-window rate limiting backed by Redis, with an in-process fallback."""

from __future__ import annotations

import logging
import threading
import time

from fastapi import HTTPException

from ..config import get_settings

log = logging.getLogger(__name__)
_local: dict[str, tuple[int, float]] = {}
_lock = threading.Lock()
_redis = None
_redis_failed_at = 0.0


def _client():
    global _redis, _redis_failed_at
    if _redis is None and time.time() - _redis_failed_at > 30:
        try:
            import redis

            _redis = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
            _redis.ping()
        except Exception:  # noqa: BLE001
            log.warning("Redis unavailable; using in-process rate limiting")
            _redis, _redis_failed_at = None, time.time()
    return _redis


def hit(key: str, limit: int, window_seconds: int = 60) -> None:
    """Count one request for ``key``; raise 429 when ``limit`` is exceeded."""
    bucket = f"llx:rl:{key}:{int(time.time() // window_seconds)}"
    count = None
    client = _client()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(bucket)
            pipe.expire(bucket, window_seconds + 5)
            count = int(pipe.execute()[0])
        except Exception:  # noqa: BLE001
            count = None
    if count is None:
        with _lock:
            n, _ = _local.get(bucket, (0, 0.0))
            _local[bucket] = (n + 1, time.time())
            count = n + 1
            if len(_local) > 10_000:
                _local.clear()
    if count > limit:
        raise HTTPException(429, "Too many requests. Wait a minute and try again.")
