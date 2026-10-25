"""
Failed password login protection.

Failed attempts are counted per client IP in Redis (``failed_logins:ip:<ip>``).
Once ``FAILED_LOGIN_MAX_ATTEMPTS`` is reached the IP is blocked until the key
expires after ``FAILED_LOGIN_BLOCK_MINUTES``. Without Redis (or when Redis
errors) an in-process tracker is used instead.
"""

import threading
import time

from flask import request

from config import (
    FAILED_LOGIN_BLOCK_MINUTES,
    FAILED_LOGIN_MAX_ATTEMPTS,
    TRUSTED_PROXY_COUNT,
)
from services.redis_client import get_redis

_KEY_PREFIX = "failed_logins:ip:"

# ip -> (failure count, expiry as time.monotonic())
_in_memory_failures: dict[str, tuple[int, float]] = {}
_lock = threading.Lock()


def get_client_ip() -> str:
    """Client IP as seen by the outermost trusted proxy.

    Each proxy appends the peer address to the right of ``X-Forwarded-For``, so
    the leading entries are client-controlled. Only the entry ``TRUSTED_PROXY_COUNT``
    positions from the right is trustworthy.
    """
    entries = [
        e.strip()
        for e in request.headers.get("X-Forwarded-For", "").split(",")
        if e.strip()
    ]
    if len(entries) >= TRUSTED_PROXY_COUNT:
        return entries[-TRUSTED_PROXY_COUNT]
    return request.remote_addr or ""


def _key(ip: str) -> str:
    return f"{_KEY_PREFIX}{ip}"


def _memory_state(ip: str) -> tuple[int, int]:
    """Return (count, remaining seconds); drops expired entries."""
    entry = _in_memory_failures.get(ip)
    if entry is None:
        return 0, 0
    count, expires = entry
    remaining = int(expires - time.monotonic() + 0.999)
    if remaining <= 0:
        del _in_memory_failures[ip]
        return 0, 0
    return count, remaining


def is_login_blocked(ip: str | None = None) -> tuple[bool, int]:
    """Return ``(blocked, remaining_seconds)`` for the given (or current) client IP."""
    ip = get_client_ip() if ip is None else ip
    r = get_redis()
    if r is not None:
        try:
            count = int(r.get(_key(ip)) or 0)
            if count >= FAILED_LOGIN_MAX_ATTEMPTS:
                ttl = r.ttl(_key(ip))
                if ttl and ttl > 0:
                    return True, ttl
            return False, 0
        except Exception:
            pass
    with _lock:
        count, remaining = _memory_state(ip)
    if count >= FAILED_LOGIN_MAX_ATTEMPTS:
        return True, remaining
    return False, 0


def record_login_failure(ip: str | None = None) -> int:
    """Count one failed attempt and return the new failure count."""
    ip = get_client_ip() if ip is None else ip
    window = FAILED_LOGIN_BLOCK_MINUTES * 60
    r = get_redis()
    if r is not None:
        try:
            count = int(r.incr(_key(ip)))
            # nx: never leave a counter without TTL, but keep the window start
            r.expire(_key(ip), window, nx=True)
            if count == FAILED_LOGIN_MAX_ATTEMPTS:
                r.expire(_key(ip), window)
            return count
        except Exception:
            pass
    with _lock:
        now = time.monotonic()
        for stale in [k for k, (_, exp) in _in_memory_failures.items() if exp <= now]:
            del _in_memory_failures[stale]
        count, _ = _memory_state(ip)
        count += 1
        previous = _in_memory_failures.get(ip)
        if previous is None or count == FAILED_LOGIN_MAX_ATTEMPTS:
            expires = time.monotonic() + window
        else:
            expires = previous[1]
        _in_memory_failures[ip] = (count, expires)
    return count


def clear_login_failures(ip: str | None = None) -> None:
    """Reset the failure counter after a successful login.

    Trade-off: an attacker owning a valid account can interleave a login to reset
    the counter; the per-second rate limiter still bounds the guess rate.
    """
    ip = get_client_ip() if ip is None else ip
    with _lock:
        _in_memory_failures.pop(ip, None)
    r = get_redis()
    if r is not None:
        try:
            r.delete(_key(ip))
        except Exception:
            pass
