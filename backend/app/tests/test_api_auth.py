"""
Tests for the JSON API auth endpoints: /api/v1/auth/*

Coverage targets:
  GET  /api/v1/auth/me              fetch current user from JWT
  POST /api/v1/auth/google/verify   exchange Google ID token for lumios JWT
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
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------

class TestApiMe:
    def test_valid_token_returns_200(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.get(f"{BASE}/me", headers=auth_header(token))
        assert res.status_code == 200

    def test_returns_account_info(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.get(f"{BASE}/me", headers=auth_header(token))
        data = res.get_json()
        assert data["email"] == "photo@test.com"
        assert data["account_type"] == "local"
        assert data["subscription"] in ("free", "standard", "premium")
        assert isinstance(data["storage_used_bytes"], int)
        assert isinstance(data["storage_limit_bytes"], int)
        assert "created_at" in data

    def test_no_token_returns_401(self, client):
        res = client.get(f"{BASE}/me")
        assert res.status_code == 401

    def test_malformed_header_returns_401(self, client, photographer_user):
        # Missing "Bearer " prefix
        token = make_token(photographer_user)
        res = client.get(f"{BASE}/me", headers={"Authorization": token})
        assert res.status_code == 401

    def test_invalid_token_returns_401(self, client):
        res = client.get(f"{BASE}/me", headers=auth_header("this.is.garbage"))
        assert res.status_code == 401

    def test_invalid_token_error_message(self, client):
        res = client.get(f"{BASE}/me", headers=auth_header("bad.token.value"))
        assert res.get_json()["error"] == "Invalid token"

    def test_expired_token_returns_401(self, client, photographer_user):
        from config import JWT_SECRET
        payload = {
            "sub": str(photographer_user.id),
            "email": photographer_user.email,
            "roles": ["photographer"],
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        expired_token = pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")
        res = client.get(f"{BASE}/me", headers=auth_header(expired_token))
        assert res.status_code == 401
        assert res.get_json()["error"] == "Token expired"

    def test_returns_subscription(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.get(f"{BASE}/me", headers=auth_header(token))
        assert res.get_json()["subscription"] == "free"

    def test_user_without_photographer_role_returns_403(self, client, regular_user):
        token = make_token(regular_user)
        res = client.get(f"{BASE}/me", headers=auth_header(token))
        assert res.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/auth/google/verify
# ---------------------------------------------------------------------------

class TestApiGoogleVerify:
    ENDPOINT = f"{BASE}/google/verify"

    def _mock_jwks(self, idinfo: dict):
        """Return context managers that fake a successful JWKS verification."""
        mock_key = MagicMock()
        return (
            patch("blueprints.api.auth.GOOGLE_FRONTEND_CLIENT_ID", "fake-client-id"),
            patch("blueprints.api.auth._google_jwks.get_signing_key_from_jwt", return_value=mock_key),
            patch("jwt.decode", return_value=idinfo),
        )

    def test_returns_501_when_not_configured(self, client):
        with patch("blueprints.api.auth.GOOGLE_FRONTEND_CLIENT_ID", None):
            res = client.post(self.ENDPOINT, json={"credential": "fake"})
        assert res.status_code == 501

    def test_missing_credential_returns_400(self, client):
        with patch("blueprints.api.auth.GOOGLE_FRONTEND_CLIENT_ID", "fake-client-id"):
            res = client.post(self.ENDPOINT, json={})
        assert res.status_code == 400

    def test_invalid_google_token_returns_401(self, client):
        with patch("blueprints.api.auth.GOOGLE_FRONTEND_CLIENT_ID", "fake-client-id"), \
             patch("blueprints.api.auth._google_jwks.get_signing_key_from_jwt",
                   side_effect=pyjwt.PyJWTError("invalid")):
            res = client.post(self.ENDPOINT, json={"credential": "bad.token.value"})
        assert res.status_code == 401
        assert "error" in res.get_json()

    def test_network_error_returns_503(self, client):
        with patch("blueprints.api.auth.GOOGLE_FRONTEND_CLIENT_ID", "fake-client-id"), \
             patch("blueprints.api.auth._google_jwks.get_signing_key_from_jwt",
                   side_effect=Exception("timeout")):
            res = client.post(self.ENDPOINT, json={"credential": "bad.token.value"})
        assert res.status_code == 503

    def test_unknown_google_account_returns_401(self, client):
        idinfo = {"email": "nobody@test.com", "sub": "google-sub-123"}
        p1, p2, p3 = self._mock_jwks(idinfo)
        with p1, p2, p3:
            res = client.post(self.ENDPOINT, json={"credential": "valid.token.value"})
        assert res.status_code == 401

    def test_successful_verify_returns_200(self, client, google_user):
        idinfo = {"email": "googleuser@test.com", "sub": "google-sub-abc"}
        p1, p2, p3 = self._mock_jwks(idinfo)
        with p1, p2, p3:
            res = client.post(self.ENDPOINT, json={"credential": "valid.token.value"})
        assert res.status_code == 200

    def test_successful_verify_response_contains_token_and_email(self, client, google_user):
        idinfo = {"email": "googleuser@test.com", "sub": "google-sub-abc"}
        p1, p2, p3 = self._mock_jwks(idinfo)
        with p1, p2, p3:
            res = client.post(self.ENDPOINT, json={"credential": "valid.token.value"})
        data = res.get_json()
        assert "token" in data
        assert data["email"] == "googleuser@test.com"
        assert isinstance(data["roles"], list)

    def test_successful_verify_token_is_valid_jwt(self, client, google_user):
        idinfo = {"email": "googleuser@test.com", "sub": "google-sub-abc"}
        p1, p2, p3 = self._mock_jwks(idinfo)
        with p1, p2, p3:
            res = client.post(self.ENDPOINT, json={"credential": "valid.token.value"})
        token = res.get_json()["token"]
        payload = decode_token(token)
        assert payload["email"] == "googleuser@test.com"

    def test_successful_verify_token_contains_roles(self, client, google_user):
        idinfo = {"email": "googleuser@test.com", "sub": "google-sub-abc"}
        p1, p2, p3 = self._mock_jwks(idinfo)
        with p1, p2, p3:
            res = client.post(self.ENDPOINT, json={"credential": "valid.token.value"})
        payload = decode_token(res.get_json()["token"])
        assert "photographer" in payload["roles"]

    def test_second_verify_with_different_sub_returns_401(self, client, google_user):
        # First verify stores the sub
        first_idinfo = {"email": "googleuser@test.com", "sub": "google-sub-abc"}
        p1, p2, p3 = self._mock_jwks(first_idinfo)
        with p1, p2, p3:
            client.post(self.ENDPOINT, json={"credential": "valid.token.value"})

        # Second verify with a different sub must be rejected
        second_idinfo = {"email": "googleuser@test.com", "sub": "different-sub"}
        p1, p2, p3 = self._mock_jwks(second_idinfo)
        with p1, p2, p3:
            res = client.post(self.ENDPOINT, json={"credential": "valid.token.value"})
        assert res.status_code == 401
        assert "token" not in res.get_json()
