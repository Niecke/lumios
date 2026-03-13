"""
Tests for the JSON API auth endpoints: /api/v1/auth/*

Coverage targets:
  POST /api/v1/auth/login           password login
  GET  /api/v1/auth/me              fetch current user from JWT
  GET  /api/v1/auth/google          OAuth redirect
  GET  /api/v1/auth/google/callback OAuth callback handling
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import jwt as pyjwt

from models import db, User, Role
from services.token import create_token, decode_token

BASE = "/api/v1/auth"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_token(user) -> str:
    """Create a valid JWT for the given user."""
    return create_token(user.id, user.email, [r.name for r in user.roles])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def photographer_role():
    role = Role(name="photographer", description="Photographer")
    db.session.add(role)
    db.session.commit()
    return role


@pytest.fixture
def photographer_user(photographer_role):
    user = User(email="photo@test.com", active=True)
    user.set_password("PhotoPass123!")
    user.roles.append(photographer_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def google_user(photographer_role):
    """A Google OAuth account (no password)."""
    user = User(email="googleuser@test.com", active=True, account_type="google")
    user.roles.append(photographer_role)
    db.session.add(user)
    db.session.commit()
    return user


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------

class TestApiLogin:
    def test_valid_credentials_returns_200(self, client, regular_user):
        res = client.post(f"{BASE}/login", json={"email": "user@test.com", "password": "UserPass123!"})
        assert res.status_code == 200

    def test_response_contains_token(self, client, regular_user):
        res = client.post(f"{BASE}/login", json={"email": "user@test.com", "password": "UserPass123!"})
        data = res.get_json()
        assert "token" in data
        assert isinstance(data["token"], str)
        assert data["token"].count(".") == 2  # JWT has 3 parts separated by dots

    def test_token_is_valid_jwt(self, client, regular_user):
        res = client.post(f"{BASE}/login", json={"email": "user@test.com", "password": "UserPass123!"})
        token = res.get_json()["token"]
        payload = decode_token(token)
        assert payload["email"] == "user@test.com"

    def test_response_contains_email_and_roles(self, client, regular_user):
        res = client.post(f"{BASE}/login", json={"email": "user@test.com", "password": "UserPass123!"})
        data = res.get_json()
        assert data["email"] == "user@test.com"
        assert isinstance(data["roles"], list)

    def test_token_roles_match_user_roles(self, client, photographer_user):
        res = client.post(f"{BASE}/login", json={"email": "photo@test.com", "password": "PhotoPass123!"})
        token = res.get_json()["token"]
        payload = decode_token(token)
        assert "photographer" in payload["roles"]

    def test_wrong_password_returns_401(self, client, regular_user):
        res = client.post(f"{BASE}/login", json={"email": "user@test.com", "password": "WrongPass!"})
        assert res.status_code == 401

    def test_wrong_password_returns_error_message(self, client, regular_user):
        res = client.post(f"{BASE}/login", json={"email": "user@test.com", "password": "WrongPass!"})
        assert "error" in res.get_json()

    def test_unknown_email_returns_401(self, client):
        res = client.post(f"{BASE}/login", json={"email": "ghost@test.com", "password": "Pass123!"})
        assert res.status_code == 401

    def test_inactive_user_returns_401(self, client, inactive_user):
        res = client.post(f"{BASE}/login", json={"email": "inactive@test.com", "password": "InactivePass123!"})
        assert res.status_code == 401

    def test_missing_body_returns_401(self, client):
        res = client.post(f"{BASE}/login", data="not json", content_type="text/plain")
        assert res.status_code == 401

    def test_empty_json_returns_401(self, client):
        res = client.post(f"{BASE}/login", json={})
        assert res.status_code == 401

    def test_email_is_stripped_of_whitespace(self, client, regular_user):
        res = client.post(f"{BASE}/login", json={"email": "  user@test.com  ", "password": "UserPass123!"})
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------

class TestApiMe:
    def test_valid_token_returns_200(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.get(f"{BASE}/me", headers=auth_header(token))
        assert res.status_code == 200

    def test_returns_email_and_roles(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.get(f"{BASE}/me", headers=auth_header(token))
        data = res.get_json()
        assert data["email"] == "photo@test.com"
        assert isinstance(data["roles"], list)

    def test_no_token_returns_401(self, client):
        res = client.get(f"{BASE}/me")
        assert res.status_code == 401

    def test_malformed_header_returns_401(self, client, regular_user):
        # Missing "Bearer " prefix
        token = make_token(regular_user)
        res = client.get(f"{BASE}/me", headers={"Authorization": token})
        assert res.status_code == 401

    def test_invalid_token_returns_401(self, client):
        res = client.get(f"{BASE}/me", headers=auth_header("this.is.garbage"))
        assert res.status_code == 401

    def test_invalid_token_error_message(self, client):
        res = client.get(f"{BASE}/me", headers=auth_header("bad.token.value"))
        assert res.get_json()["error"] == "Invalid token"

    def test_expired_token_returns_401(self, client, regular_user):
        # Build a token that expired 1 second ago
        from config import JWT_SECRET
        payload = {
            "sub": str(regular_user.id),
            "email": regular_user.email,
            "roles": [],
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        expired_token = pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")
        res = client.get(f"{BASE}/me", headers=auth_header(expired_token))
        assert res.status_code == 401
        assert res.get_json()["error"] == "Token expired"

    def test_token_with_roles_returns_roles(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.get(f"{BASE}/me", headers=auth_header(token))
        assert "photographer" in res.get_json()["roles"]


# ---------------------------------------------------------------------------
# GET /api/v1/auth/google
# ---------------------------------------------------------------------------

class TestApiGoogleLogin:
    def test_returns_501_when_not_configured(self, client):
        # GOOGLE_CLIENT_ID is not set in the test environment
        with patch("blueprints.api.auth.GOOGLE_CLIENT_ID", None):
            res = client.get(f"{BASE}/google")
        assert res.status_code == 501

    def test_returns_error_json_when_not_configured(self, client):
        with patch("blueprints.api.auth.GOOGLE_CLIENT_ID", None):
            res = client.get(f"{BASE}/google")
        assert "error" in res.get_json()

    def test_redirects_to_google_when_configured(self, client):
        mock_redirect = MagicMock(return_value=("", 302, {"Location": "https://accounts.google.com/o/oauth2/auth"}))
        with patch("blueprints.api.auth.GOOGLE_CLIENT_ID", "fake-client-id"), \
             patch("blueprints.api.auth.oauth.google.authorize_redirect", mock_redirect):
            res = client.get(f"{BASE}/google")
        mock_redirect.assert_called_once()


# ---------------------------------------------------------------------------
# GET /api/v1/auth/google/callback
# ---------------------------------------------------------------------------

class TestApiGoogleCallback:
    def test_exchange_failure_redirects_to_login_with_error(self, client):
        with patch("blueprints.api.auth.oauth.google.authorize_access_token", side_effect=Exception("failed")):
            res = client.get(f"{BASE}/google/callback", follow_redirects=False)
        assert res.status_code == 302
        assert "error=google_failed" in res.location

    def test_missing_userinfo_redirects_to_login_with_error(self, client):
        with patch("blueprints.api.auth.oauth.google.authorize_access_token", return_value={}):
            res = client.get(f"{BASE}/google/callback", follow_redirects=False)
        assert res.status_code == 302
        assert "error=google_failed" in res.location

    def test_unknown_google_account_redirects_with_error(self, client):
        fake_token = {"userinfo": {"email": "nobody@test.com", "sub": "google-sub-123"}}
        with patch("blueprints.api.auth.oauth.google.authorize_access_token", return_value=fake_token):
            res = client.get(f"{BASE}/google/callback", follow_redirects=False)
        assert res.status_code == 302
        assert "error=" in res.location
        assert "google_failed" not in res.location  # it's an AuthError message, not google_failed

    def test_successful_callback_redirects_to_frontend_login(self, client, google_user):
        fake_token = {"userinfo": {"email": "googleuser@test.com", "sub": "google-sub-abc"}}
        with patch("blueprints.api.auth.oauth.google.authorize_access_token", return_value=fake_token):
            res = client.get(f"{BASE}/google/callback", follow_redirects=False)
        assert res.status_code == 302
        assert "#token=" in res.location

    def test_successful_callback_token_is_valid_jwt(self, client, google_user):
        fake_token = {"userinfo": {"email": "googleuser@test.com", "sub": "google-sub-abc"}}
        with patch("blueprints.api.auth.oauth.google.authorize_access_token", return_value=fake_token):
            res = client.get(f"{BASE}/google/callback", follow_redirects=False)
        fragment = res.location.split("#token=")[1]
        payload = decode_token(fragment)
        assert payload["email"] == "googleuser@test.com"

    def test_successful_callback_token_contains_roles(self, client, google_user):
        fake_token = {"userinfo": {"email": "googleuser@test.com", "sub": "google-sub-abc"}}
        with patch("blueprints.api.auth.oauth.google.authorize_access_token", return_value=fake_token):
            res = client.get(f"{BASE}/google/callback", follow_redirects=False)
        fragment = res.location.split("#token=")[1]
        payload = decode_token(fragment)
        assert "photographer" in payload["roles"]

    def test_second_login_verifies_stored_sub(self, client, google_user):
        # First login stores the sub
        fake_token = {"userinfo": {"email": "googleuser@test.com", "sub": "google-sub-abc"}}
        with patch("blueprints.api.auth.oauth.google.authorize_access_token", return_value=fake_token):
            client.get(f"{BASE}/google/callback")

        # Second login with different sub should fail
        fake_token_bad = {"userinfo": {"email": "googleuser@test.com", "sub": "different-sub"}}
        with patch("blueprints.api.auth.oauth.google.authorize_access_token", return_value=fake_token_bad):
            res = client.get(f"{BASE}/google/callback", follow_redirects=False)
        assert "error=" in res.location
        assert "#token=" not in res.location
