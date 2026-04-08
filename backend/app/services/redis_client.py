"""
Shared Redis client with connection pooling.

All Redis consumers in the app should import from here instead of
creating their own ``redis.from_url()`` clients.  When ``REDIS_URL``
is not configured the helpers return ``None`` / silently no-op so the
rest of the application keeps working without Redis.
"""

import json
import logging

import redis as _redis_lib

from config import REDIS_URL

logger = logging.getLogger(__name__)

# -- connection pool (lazy, created on first call) --------------------------

_pool: _redis_lib.ConnectionPool | None = None
_client: _redis_lib.Redis | None = None

# flask-session stores binary data and must NOT use decode_responses.
_session_pool: _redis_lib.ConnectionPool | None = None
_session_client: _redis_lib.Redis | None = None


def get_redis() -> _redis_lib.Redis | None:
    """Return a shared Redis client (``decode_responses=True``).

    Returns ``None`` when ``REDIS_URL`` is not set.
    """
    global _pool, _client
    if not REDIS_URL:
        return None
    if _client is None:
        _pool = _redis_lib.ConnectionPool.from_url(
            REDIS_URL, decode_responses=True
        )
        _client = _redis_lib.Redis(connection_pool=_pool)
    return _client


def get_redis_session() -> _redis_lib.Redis | None:
    """Return a shared Redis client **without** ``decode_responses``.

    Intended for flask-session which stores binary pickle data.
    Returns ``None`` when ``REDIS_URL`` is not set.
    """
    global _session_pool, _session_client
    if not REDIS_URL:
        return None
    if _session_client is None:
        _session_pool = _redis_lib.ConnectionPool.from_url(REDIS_URL)
        _session_client = _redis_lib.Redis(connection_pool=_session_pool)
    return _session_client


# -- lightweight cache helpers ----------------------------------------------


def cache_get(key: str):
    """Return the cached JSON value for *key*, or ``None`` on miss."""
    r = get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def cache_set(key: str, value, ttl: int = 300) -> None:
    """Store a JSON-serialisable *value* under *key* with a TTL (seconds)."""
    r = get_redis()
    if r is None:
        return
    try:
        r.setex(key, ttl, json.dumps(value))
    except Exception:
        pass


def cache_delete(key: str) -> None:
    """Delete a single cache key."""
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception:
        pass


def cache_delete_pattern(pattern: str) -> None:
    """Delete all keys matching *pattern* (uses ``SCAN``).  Use sparingly."""
    r = get_redis()
    if r is None:
        return
    try:
        cursor: int = 0
        while True:
            cursor, keys = r.scan(cursor, match=pattern, count=100)
            if keys:
                r.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        pass
