"""
Unit tests for the shared Redis client module.

Tests exercise both the "Redis available" and "Redis unavailable" (REDIS_URL=None)
code paths using mock objects — no real Redis server is needed.
"""

import os
import sys

os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long!")
os.environ.setdefault("JWT_SECRET", "test-secret-key-at-least-32-chars-long!")
os.environ.setdefault("DEBUG", "true")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from unittest.mock import patch, MagicMock
import json
import pytest


# ---------------------------------------------------------------------------
# Tests with REDIS_URL = None (no Redis)
# ---------------------------------------------------------------------------


class TestNoRedis:
    """When REDIS_URL is not set, all helpers should return None / no-op."""

    def test_get_redis_returns_none(self):
        import services.redis_client as mod

        # Reset module state
        mod._client = None
        mod._pool = None
        with patch.object(mod, "REDIS_URL", None):
            assert mod.get_redis() is None

    def test_get_redis_session_returns_none(self):
        import services.redis_client as mod

        mod._session_client = None
        mod._session_pool = None
        with patch.object(mod, "REDIS_URL", None):
            assert mod.get_redis_session() is None

    def test_cache_get_returns_none(self):
        import services.redis_client as mod

        with patch.object(mod, "get_redis", return_value=None):
            assert mod.cache_get("any_key") is None

    def test_cache_set_noop(self):
        import services.redis_client as mod

        with patch.object(mod, "get_redis", return_value=None):
            # Should not raise
            mod.cache_set("key", {"data": 1}, ttl=60)

    def test_cache_delete_noop(self):
        import services.redis_client as mod

        with patch.object(mod, "get_redis", return_value=None):
            mod.cache_delete("key")

    def test_cache_delete_pattern_noop(self):
        import services.redis_client as mod

        with patch.object(mod, "get_redis", return_value=None):
            mod.cache_delete_pattern("prefix:*")


# ---------------------------------------------------------------------------
# Tests with a mock Redis client
# ---------------------------------------------------------------------------


class TestWithRedis:
    """When REDIS_URL is set, helpers should delegate to the Redis client."""

    def _make_mock_redis(self):
        mock = MagicMock()
        return mock

    def test_cache_get_hit(self):
        import services.redis_client as mod

        mock_r = self._make_mock_redis()
        mock_r.get.return_value = json.dumps({"count": 42})

        with patch.object(mod, "get_redis", return_value=mock_r):
            result = mod.cache_get("test:key")
            assert result == {"count": 42}
            mock_r.get.assert_called_once_with("test:key")

    def test_cache_get_miss(self):
        import services.redis_client as mod

        mock_r = self._make_mock_redis()
        mock_r.get.return_value = None

        with patch.object(mod, "get_redis", return_value=mock_r):
            assert mod.cache_get("missing") is None

    def test_cache_get_handles_exception(self):
        import services.redis_client as mod

        mock_r = self._make_mock_redis()
        mock_r.get.side_effect = ConnectionError("Redis down")

        with patch.object(mod, "get_redis", return_value=mock_r):
            assert mod.cache_get("key") is None

    def test_cache_set_stores_json(self):
        import services.redis_client as mod

        mock_r = self._make_mock_redis()

        with patch.object(mod, "get_redis", return_value=mock_r):
            mod.cache_set("key", {"data": True}, ttl=120)
            mock_r.setex.assert_called_once_with(
                "key", 120, json.dumps({"data": True})
            )

    def test_cache_set_handles_exception(self):
        import services.redis_client as mod

        mock_r = self._make_mock_redis()
        mock_r.setex.side_effect = ConnectionError("Redis down")

        with patch.object(mod, "get_redis", return_value=mock_r):
            # Should not raise
            mod.cache_set("key", "value", ttl=60)

    def test_cache_delete_calls_redis(self):
        import services.redis_client as mod

        mock_r = self._make_mock_redis()

        with patch.object(mod, "get_redis", return_value=mock_r):
            mod.cache_delete("mykey")
            mock_r.delete.assert_called_once_with("mykey")

    def test_cache_delete_pattern_scans_and_deletes(self):
        import services.redis_client as mod

        mock_r = self._make_mock_redis()
        # Simulate a single SCAN iteration that returns keys, then cursor 0
        mock_r.scan.return_value = (0, ["prefix:a", "prefix:b"])

        with patch.object(mod, "get_redis", return_value=mock_r):
            mod.cache_delete_pattern("prefix:*")
            mock_r.scan.assert_called_once_with(0, match="prefix:*", count=100)
            mock_r.delete.assert_called_once_with("prefix:a", "prefix:b")

    def test_cache_delete_pattern_handles_exception(self):
        import services.redis_client as mod

        mock_r = self._make_mock_redis()
        mock_r.scan.side_effect = ConnectionError("Redis down")

        with patch.object(mod, "get_redis", return_value=mock_r):
            # Should not raise
            mod.cache_delete_pattern("prefix:*")

    def test_cache_set_string_value(self):
        """cache_set should handle plain string values (e.g. presigned URLs)."""
        import services.redis_client as mod

        mock_r = self._make_mock_redis()

        with patch.object(mod, "get_redis", return_value=mock_r):
            mod.cache_set("presigned:abc", "https://example.com/signed", ttl=1800)
            mock_r.setex.assert_called_once_with(
                "presigned:abc", 1800, json.dumps("https://example.com/signed")
            )

    def test_cache_get_string_value(self):
        """cache_get should return plain string values."""
        import services.redis_client as mod

        mock_r = self._make_mock_redis()
        mock_r.get.return_value = json.dumps("https://example.com/signed")

        with patch.object(mod, "get_redis", return_value=mock_r):
            result = mod.cache_get("presigned:abc")
            assert result == "https://example.com/signed"
