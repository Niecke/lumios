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
