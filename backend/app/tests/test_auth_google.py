"""
Tests for the SSR Google OAuth routes in blueprints/auth.py:

  GET  /auth/google         initiates the OAuth dance
  GET  /auth/callback       handles the callback from Google
"""
import pytest
from unittest.mock import patch, MagicMock

from models import db, User, Role


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def google_user():
    role = Role(name="admin", description="Administrator")
    db.session.add(role)
    user = User(email="guser@test.com", active=True, account_type="google")
    user.roles.append(role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def inactive_google_user():
    user = User(email="inactive.google@test.com", active=False, account_type="google")
    db.session.add(user)
    db.session.commit()
    return user


# ---------------------------------------------------------------------------
# GET /auth/google
# ---------------------------------------------------------------------------

class TestGoogleLogin:
    def test_redirects_to_login_when_not_configured(self, client):
        with patch("blueprints.auth.GOOGLE_CLIENT_ID", None):
            res = client.get("/auth/google", follow_redirects=False)
        assert res.status_code == 302
        assert "/login" in res.location

    def test_flashes_error_when_not_configured(self, client):
        with patch("blueprints.auth.GOOGLE_CLIENT_ID", None):
            res = client.get("/auth/google", follow_redirects=True)
        assert b"Google login is not configured" in res.data

    def test_redirects_to_google_when_configured(self, client):
        mock_redirect = MagicMock(
            return_value=("", 302, {"Location": "https://accounts.google.com/o/oauth2/auth"})
        )
        with patch("blueprints.auth.GOOGLE_CLIENT_ID", "fake-client-id"), \
             patch("blueprints.auth.oauth.google.authorize_redirect", mock_redirect):
            res = client.get("/auth/google")
        mock_redirect.assert_called_once()

    def test_authorize_redirect_uses_correct_callback_uri(self, client):
        captured = {}

        def fake_redirect(uri, **kwargs):
            captured["uri"] = uri
            return ("", 302, {"Location": "https://accounts.google.com"})

        with patch("blueprints.auth.GOOGLE_CLIENT_ID", "fake-client-id"), \
             patch("blueprints.auth.oauth.google.authorize_redirect", fake_redirect):
            client.get("/auth/google")

        assert captured["uri"].endswith("/auth/callback")


# ---------------------------------------------------------------------------
# GET /auth/callback
# ---------------------------------------------------------------------------

class TestGoogleCallback:
    def test_exchange_failure_redirects_to_login(self, client):
        with patch("blueprints.auth.oauth.google.authorize_access_token", side_effect=Exception("failed")):
            res = client.get("/auth/callback", follow_redirects=False)
        assert res.status_code == 302
        assert "/login" in res.location

    def test_exchange_failure_flashes_error(self, client):
        with patch("blueprints.auth.oauth.google.authorize_access_token", side_effect=Exception("failed")):
            res = client.get("/auth/callback", follow_redirects=True)
        assert b"Google login failed" in res.data

    def test_missing_userinfo_redirects_to_login(self, client):
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value={}):
            res = client.get("/auth/callback", follow_redirects=False)
        assert res.status_code == 302
        assert "/login" in res.location

    def test_missing_userinfo_flashes_error(self, client):
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value={}):
            res = client.get("/auth/callback", follow_redirects=True)
        assert b"Google login failed" in res.data

    def test_unknown_email_redirects_to_login(self, client):
        fake_token = {"userinfo": {"email": "nobody@test.com", "sub": "sub-123"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=fake_token):
            res = client.get("/auth/callback", follow_redirects=False)
        assert res.status_code == 302
        assert "/login" in res.location

    def test_unknown_email_flashes_error_message(self, client):
        fake_token = {"userinfo": {"email": "nobody@test.com", "sub": "sub-123"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=fake_token):
            res = client.get("/auth/callback", follow_redirects=True)
        assert b"No account found" in res.data

    def test_inactive_user_redirects_to_login(self, client, inactive_google_user):
        fake_token = {"userinfo": {"email": "inactive.google@test.com", "sub": "sub-456"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=fake_token):
            res = client.get("/auth/callback", follow_redirects=False)
        assert res.status_code == 302
        assert "/login" in res.location

    def test_successful_login_redirects_to_admin(self, client, google_user):
        fake_token = {"userinfo": {"email": "guser@test.com", "sub": "sub-abc"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=fake_token):
            res = client.get("/auth/callback", follow_redirects=False)
        assert res.status_code == 302
        assert res.location.endswith("/")

    def test_successful_login_creates_session(self, client, google_user):
        fake_token = {"userinfo": {"email": "guser@test.com", "sub": "sub-abc"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=fake_token):
            client.get("/auth/callback")
        with client.session_transaction() as sess:
            assert sess.get("user_id") == google_user.id

    def test_successful_login_stores_google_sub(self, client, google_user):
        fake_token = {"userinfo": {"email": "guser@test.com", "sub": "sub-abc"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=fake_token):
            client.get("/auth/callback")
        db.session.refresh(google_user)
        assert google_user.auth_string == "sub-abc"

    def test_second_login_with_wrong_sub_redirects_to_login(self, client, google_user):
        # First login — stores the sub
        first = {"userinfo": {"email": "guser@test.com", "sub": "sub-abc"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=first):
            client.get("/auth/callback")

        # Second login — different sub should be rejected
        second = {"userinfo": {"email": "guser@test.com", "sub": "different-sub"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=second):
            res = client.get("/auth/callback", follow_redirects=False)
        assert res.status_code == 302
        assert "/login" in res.location

    def test_second_login_with_wrong_sub_flashes_error(self, client, google_user):
        first = {"userinfo": {"email": "guser@test.com", "sub": "sub-abc"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=first):
            client.get("/auth/callback")

        second = {"userinfo": {"email": "guser@test.com", "sub": "different-sub"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=second):
            res = client.get("/auth/callback", follow_redirects=True)
        assert b"mismatch" in res.data.lower()

    def test_local_account_cannot_use_google_callback(self, client, regular_user):
        # regular_user has account_type='local' — Google callback should reject it
        fake_token = {"userinfo": {"email": "user@test.com", "sub": "sub-xyz"}}
        with patch("blueprints.auth.oauth.google.authorize_access_token", return_value=fake_token):
            res = client.get("/auth/callback", follow_redirects=False)
        assert res.status_code == 302
        assert "/login" in res.location
