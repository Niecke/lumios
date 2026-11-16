"""
Tests for the /health endpoint.
"""

import json
import sys

import pytest

from blueprints import health as health_module
from services.schema import SchemaStatus


def test_python_runtime_version():
    assert sys.version_info[:2] == (3, 14)


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_json(self, client):
        response = client.get("/health")
        assert response.content_type.startswith("application/json")

    def test_health_contains_status_field(self, client):
        response = client.get("/health")
        data = json.loads(response.data)
        assert "status" in data

    def test_health_reports_healthy(self, client):
        response = client.get("/health")
        data = json.loads(response.data)
        assert data["status"] == "healthy"

    def test_health_accessible_without_login(self, client):
        # Health check must be publicly accessible for load balancer probes
        response = client.get("/health")
        assert response.status_code == 200


class TestVersionEndpoint:
    def test_version_returns_200(self, client):
        response = client.get("/version")
        assert response.status_code == 200
        assert response.content_type.startswith("application/json")

    def test_version_contains_fields(self, client):
        data = json.loads(client.get("/version").data)
        assert "commit" in data
        assert "version" in data
        assert "built_at" in data

    def test_version_exposes_nothing_else(self, client):
        data = json.loads(client.get("/version").data)
        assert set(data) == {"commit", "version", "built_at"}

    def test_version_json_alias(self, client):
        assert client.get("/version.json").data == client.get("/version").data


class TestHealthReadyEndpoint:
    @pytest.fixture(autouse=True)
    def reset_logged_state(self, app, caplog, monkeypatch):
        monkeypatch.setattr(health_module, "_last_logged_missing", ())
        # The app logger does not propagate and Alembic's fileConfig may have
        # disabled it: hand caplog's handler to it directly.
        monkeypatch.setattr(app.logger, "disabled", False)
        app.logger.addHandler(caplog.handler)
        yield
        app.logger.removeHandler(caplog.handler)

    @staticmethod
    def _behind(monkeypatch, missing=("abc123def456",)):
        status = SchemaStatus(False, ("000000000000",), ("abc123def456",), missing)
        monkeypatch.setattr(health_module, "schema_status", lambda conn: status)

    def test_ready_returns_200_at_head(self, client):
        response = client.get("/health/ready")

        assert response.status_code == 200
        assert json.loads(response.data) == {"status": "healthy"}

    def test_ready_returns_503_when_schema_is_behind(self, client, monkeypatch):
        self._behind(monkeypatch)

        response = client.get("/health/ready")

        assert response.status_code == 503
        assert json.loads(response.data) == {"status": "schema_not_ready"}

    def test_body_carries_no_revision_id(self, client, monkeypatch):
        self._behind(monkeypatch)

        body = client.get("/health/ready").get_data(as_text=True)

        assert "abc123def456" not in body

    def test_ready_returns_503_when_database_ping_fails(self, client, monkeypatch):
        monkeypatch.setattr(health_module, "_ping_db", lambda: False)

        response = client.get("/health/ready")

        assert response.status_code == 503
        assert json.loads(response.data) == {"status": "unhealthy"}

    def test_ready_returns_503_when_redis_ping_fails(self, client, monkeypatch):
        monkeypatch.setattr(health_module, "_ping_redis", lambda: False)

        assert client.get("/health/ready").status_code == 503

    def test_ready_returns_503_when_schema_query_fails(self, client, monkeypatch):
        def boom(conn):
            raise RuntimeError("down")

        monkeypatch.setattr(health_module, "schema_status", boom)

        response = client.get("/health/ready")

        assert response.status_code == 503
        assert json.loads(response.data) == {"status": "unhealthy"}

    def test_warning_names_the_revisions_and_is_logged_once(self, client, monkeypatch, caplog):
        self._behind(monkeypatch)

        with caplog.at_level("WARNING"):
            client.get("/health/ready")
            client.get("/health/ready")

        warnings = [r for r in caplog.records if "Database schema not ready" in r.getMessage()]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "abc123def456" in message
        assert "database at 000000000000" in message
        assert "code head abc123def456" in message

    def test_recovery_is_logged_and_a_new_failure_warns_again(self, client, monkeypatch, caplog):
        behind = SchemaStatus(False, ("000000000000",), ("abc123def456",), ("abc123def456",))
        current = {"status": behind}
        monkeypatch.setattr(health_module, "schema_status", lambda conn: current["status"])

        with caplog.at_level("INFO"):
            client.get("/health/ready")
            current["status"] = SchemaStatus(True, ("abc123def456",), ("abc123def456",), ())
            assert client.get("/health/ready").status_code == 200
            current["status"] = behind
            client.get("/health/ready")

        messages = [r.getMessage() for r in caplog.records]
        assert sum("Database schema not ready" in m for m in messages) == 2
        assert sum("Database schema ready" in m for m in messages) == 1

    def test_plain_health_ignores_the_schema(self, client, monkeypatch):
        self._behind(monkeypatch)

        assert client.get("/health").status_code == 200
