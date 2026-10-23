"""
Tests for the /health endpoint.
"""

import json


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
