"""
Shared Redis client with connection pooling.

All Redis consumers in the app should import from here instead of
creating their own ``redis.from_url()`` clients.  When ``REDIS_URL``
is not configured the helpers return ``None`` / silently no-op so the
rest of the application keeps working without Redis.
"""

import json
import logging
import time

import redis as _redis_lib

from config import REDIS_URL

logger = logging.getLogger(__name__)

# -- connection pool (lazy, created on first call) --------------------------

# One pool for the whole backend.  It does NOT use ``decode_responses``:
# flask-session and the binary preview cache store raw bytes, so every
# consumer gets ``bytes`` back and decodes where it needs text.
_pool: _redis_lib.ConnectionPool | None = None
_client: _redis_lib.Redis | None = None


def get_redis() -> _redis_lib.Redis | None:
    """Return the shared Redis client (binary responses, pooled).

    Returns ``None`` when ``REDIS_URL`` is not set.
    """
    global _pool, _client
    if not REDIS_URL:
        return None
    if _client is None:
        _pool = _redis_lib.ConnectionPool.from_url(REDIS_URL)
        _client = _redis_lib.Redis(connection_pool=_pool)
    return _client


def get_redis_bytes() -> _redis_lib.Redis | None:
    """Return the shared Redis client for raw ``bytes`` values."""
    return get_redis()


def get_redis_session() -> _redis_lib.Redis | None:
    """Return the shared Redis client for flask-session (binary pickle data)."""
    return get_redis()


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


# -- binary cache helpers ---------------------------------------------------


def cache_get_bytes(key: str) -> bytes | None:
    """Return the raw bytes stored under *key*, or ``None`` on miss / no Redis."""
    r = get_redis_bytes()
    if r is None:
        return None
    try:
        return r.get(key)
    except Exception:
        return None


def cache_set_bytes(key: str, value: bytes, ttl: int = 3600) -> None:
    """Store raw *value* under *key* with a TTL (seconds)."""
    r = get_redis_bytes()
    if r is None:
        return
    try:
        r.setex(key, ttl, value)
    except Exception:
        pass


def cache_set_bytes_capped(
    key: str, value: bytes, index_key: str, max_entries: int, ttl: int = 3600
) -> None:
    """Store *value* and keep at most *max_entries* keys tracked in *index_key*.

    *index_key* is a sorted set (score = insertion time) of the keys of one
    group, e.g. all cached previews of a library.  When the group grows past
    *max_entries* the oldest keys are deleted, so the group cannot fill Redis.
    """
    r = get_redis_bytes()
    if r is None:
        return
    try:
        pipe = r.pipeline()
        now = time.time()
        pipe.setex(key, ttl, value)
        pipe.zadd(index_key, {key: now})
        # entries whose key already expired by TTL must not count toward the cap
        pipe.zremrangebyscore(index_key, 0, now - ttl)
        pipe.expire(index_key, ttl)
        # everything except the newest max_entries keys
        pipe.zrange(index_key, 0, -(max_entries + 1))
        old = pipe.execute()[-1]
        if old:
            trim = r.pipeline()
            trim.delete(*old)
            trim.zrem(index_key, *old)
            trim.execute()
    except Exception:
        pass
