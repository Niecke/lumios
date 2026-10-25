"""
Unit tests for services/login_protection.py (Redis and in-memory paths).
"""

from unittest.mock import MagicMock, patch

import pytest

from config import FAILED_LOGIN_BLOCK_MINUTES, FAILED_LOGIN_MAX_ATTEMPTS
from services import login_protection
from services.login_protection import (
    clear_login_failures,
    is_login_blocked,
    record_login_failure,
)

IP = "203.0.113.7"
KEY = f"failed_logins:ip:{IP}"


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        v = self.values.get(key)
        return None if v is None else str(v)

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds):
        self.ttls[key] = seconds

    def ttl(self, key):
        return self.ttls.get(key, -2)

    def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)


@pytest.fixture
def fake_redis():
    r = FakeRedis()
    with patch.object(login_protection, "get_redis", return_value=r):
        yield r


@pytest.fixture
def no_redis():
    with patch.object(login_protection, "get_redis", return_value=None):
        yield


def test_record_failure_increments_counter_and_sets_ttl(fake_redis):
    assert record_login_failure(IP) == 1
    assert record_login_failure(IP) == 2
    assert fake_redis.values[KEY] == 2
    assert fake_redis.ttls[KEY] == FAILED_LOGIN_BLOCK_MINUTES * 60


def test_is_login_blocked_false_under_threshold(fake_redis):
    for _ in range(FAILED_LOGIN_MAX_ATTEMPTS - 1):
        record_login_failure(IP)
    assert is_login_blocked(IP) == (False, 0)


def test_is_login_blocked_true_at_threshold(fake_redis):
    for _ in range(FAILED_LOGIN_MAX_ATTEMPTS):
        record_login_failure(IP)
    assert is_login_blocked(IP) == (True, FAILED_LOGIN_BLOCK_MINUTES * 60)


def test_other_ip_not_blocked(fake_redis):
    for _ in range(FAILED_LOGIN_MAX_ATTEMPTS):
        record_login_failure(IP)
    assert is_login_blocked("198.51.100.1") == (False, 0)


def test_clear_login_failures_deletes_key(fake_redis):
    record_login_failure(IP)
    clear_login_failures(IP)
    assert KEY not in fake_redis.values
    assert is_login_blocked(IP) == (False, 0)


def test_in_memory_fallback_when_redis_none(no_redis):
    for _ in range(FAILED_LOGIN_MAX_ATTEMPTS):
        assert is_login_blocked(IP)[0] is False
        record_login_failure(IP)
    blocked, remaining = is_login_blocked(IP)
    assert blocked is True
    assert 0 < remaining <= FAILED_LOGIN_BLOCK_MINUTES * 60
    clear_login_failures(IP)
    assert is_login_blocked(IP) == (False, 0)


def test_in_memory_block_expires(no_redis):
    with patch.object(login_protection.time, "monotonic", return_value=1000.0):
        for _ in range(FAILED_LOGIN_MAX_ATTEMPTS):
            record_login_failure(IP)
        assert is_login_blocked(IP)[0] is True
    later = 1000.0 + FAILED_LOGIN_BLOCK_MINUTES * 60 + 1
    with patch.object(login_protection.time, "monotonic", return_value=later):
        assert is_login_blocked(IP) == (False, 0)


def test_redis_exception_fails_open_gracefully():
    broken = MagicMock()
    broken.get.side_effect = ConnectionError("down")
    broken.incr.side_effect = ConnectionError("down")
    broken.delete.side_effect = ConnectionError("down")
    with patch.object(login_protection, "get_redis", return_value=broken):
        for _ in range(FAILED_LOGIN_MAX_ATTEMPTS):
            record_login_failure(IP)
        assert is_login_blocked(IP)[0] is True
        clear_login_failures(IP)
        assert is_login_blocked(IP) == (False, 0)
