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
            patch(
                "blueprints.api.auth._google_jwks.get_signing_key_from_jwt",
                return_value=mock_key,
            ),
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
        with patch(
            "blueprints.api.auth.GOOGLE_FRONTEND_CLIENT_ID", "fake-client-id"
        ), patch(
            "blueprints.api.auth._google_jwks.get_signing_key_from_jwt",
            side_effect=pyjwt.PyJWTError("invalid"),
        ):
            res = client.post(self.ENDPOINT, json={"credential": "bad.token.value"})
        assert res.status_code == 401
        assert "error" in res.get_json()

    def test_network_error_returns_503(self, client):
        with patch(
            "blueprints.api.auth.GOOGLE_FRONTEND_CLIENT_ID", "fake-client-id"
        ), patch(
            "blueprints.api.auth._google_jwks.get_signing_key_from_jwt",
            side_effect=Exception("timeout"),
        ):
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

    def test_successful_verify_response_contains_token_and_email(
        self, client, google_user
    ):
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


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------


class TestApiPasswordLogin:
    ENDPOINT = f"{BASE}/login"

    def test_missing_email_returns_400(self, client):
        res = client.post(self.ENDPOINT, json={"password": "pass"})
        assert res.status_code == 400

    def test_missing_password_returns_400(self, client):
        res = client.post(self.ENDPOINT, json={"email": "photo@test.com"})
        assert res.status_code == 400

    def test_wrong_password_returns_401(self, client, photographer_user):
        res = client.post(
            self.ENDPOINT, json={"email": "photo@test.com", "password": "WrongPass!"}
        )
        assert res.status_code == 401

    def test_unknown_email_returns_401(self, client):
        res = client.post(
            self.ENDPOINT, json={"email": "nobody@test.com", "password": "pass"}
        )
        assert res.status_code == 401

    def test_inactive_user_returns_403(self, client, inactive_user):
        res = client.post(
            self.ENDPOINT,
            json={"email": "inactive@test.com", "password": "InactivePass123!"},
        )
        assert res.status_code == 403

    def test_google_account_returns_401(self, client, google_user):
        res = client.post(
            self.ENDPOINT, json={"email": "googleuser@test.com", "password": "anything"}
        )
        assert res.status_code == 401

    def test_successful_login_returns_200(self, client, photographer_user):
        res = client.post(
            self.ENDPOINT, json={"email": "photo@test.com", "password": "PhotoPass123!"}
        )
        assert res.status_code == 200

    def test_successful_login_returns_token(self, client, photographer_user):
        res = client.post(
            self.ENDPOINT, json={"email": "photo@test.com", "password": "PhotoPass123!"}
        )
        data = res.get_json()
        assert "token" in data
        payload = decode_token(data["token"])
        assert payload["email"] == "photo@test.com"

    def test_successful_login_returns_roles(self, client, photographer_user):
        res = client.post(
            self.ENDPOINT, json={"email": "photo@test.com", "password": "PhotoPass123!"}
        )
        data = res.get_json()
        assert "photographer" in data["roles"]

    def test_successful_login_returns_account_type(self, client, photographer_user):
        res = client.post(
            self.ENDPOINT, json={"email": "photo@test.com", "password": "PhotoPass123!"}
        )
        assert res.get_json()["account_type"] == "local"


# ---------------------------------------------------------------------------
# POST /api/v1/auth/change_password
# ---------------------------------------------------------------------------


class TestApiChangePassword:
    ENDPOINT = f"{BASE}/change_password"

    def test_no_auth_returns_401(self, client):
        res = client.post(
            self.ENDPOINT, json={"current_password": "old", "new_password": "new"}
        )
        assert res.status_code == 401

    def test_google_account_returns_400(self, client, google_user):
        token = make_token(google_user)
        res = client.post(
            self.ENDPOINT,
            json={"current_password": "x", "new_password": "y"},
            headers=auth_header(token),
        )
        assert res.status_code == 400
        assert "local" in res.get_json()["error"]

    def test_missing_current_password_returns_400(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.post(
            self.ENDPOINT,
            json={"new_password": "NewPass123!"},
            headers=auth_header(token),
        )
        assert res.status_code == 400

    def test_missing_new_password_returns_400(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.post(
            self.ENDPOINT,
            json={"current_password": "PhotoPass123!"},
            headers=auth_header(token),
        )
        assert res.status_code == 400

    def test_wrong_current_password_returns_401(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.post(
            self.ENDPOINT,
            json={"current_password": "WrongPass!", "new_password": "NewPass123!"},
            headers=auth_header(token),
        )
        assert res.status_code == 401

    def test_too_short_new_password_returns_400(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.post(
            self.ENDPOINT,
            json={"current_password": "PhotoPass123!", "new_password": "short"},
            headers=auth_header(token),
        )
        assert res.status_code == 400

    def test_successful_change_returns_200(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.post(
            self.ENDPOINT,
            json={"current_password": "PhotoPass123!", "new_password": "NewPass123!"},
            headers=auth_header(token),
        )
        assert res.status_code == 200
        assert res.get_json()["ok"] is True

    def test_old_password_rejected_after_change(self, client, photographer_user):
        token = make_token(photographer_user)
        client.post(
            self.ENDPOINT,
            json={"current_password": "PhotoPass123!", "new_password": "NewPass123!"},
            headers=auth_header(token),
        )
        # Old password must now fail
        res = client.post(
            self.ENDPOINT,
            json={
                "current_password": "PhotoPass123!",
                "new_password": "AnotherPass123!",
            },
            headers=auth_header(token),
        )
        assert res.status_code == 401

    def test_new_password_works_after_change(self, client, photographer_user):
        token = make_token(photographer_user)
        client.post(
            self.ENDPOINT,
            json={"current_password": "PhotoPass123!", "new_password": "NewPass123!"},
            headers=auth_header(token),
        )
        res = client.post(
            f"{BASE}/login", json={"email": "photo@test.com", "password": "NewPass123!"}
        )
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/auth/activate  — token expiry
# ---------------------------------------------------------------------------


class TestActivateTokenExpiry:
    ENDPOINT = f"{BASE}/activate"

    @pytest.fixture
    def pending_user(self, photographer_role):
        user = User(
            email="pending@test.com",
            active=False,
            activation_pending=True,
            activation_token="valid-token-abc",
            activation_token_created_at=datetime.now(timezone.utc),
        )
        user.set_password("PendingPass123!")
        user.roles.append(photographer_role)
        db.session.add(user)
        db.session.commit()
        return user

    @pytest.fixture
    def expired_user(self, photographer_role):
        user = User(
            email="expired@test.com",
            active=False,
            activation_pending=True,
            activation_token="expired-token-xyz",
            activation_token_created_at=datetime.now(timezone.utc)
            - timedelta(hours=73),
        )
        user.set_password("ExpiredPass123!")
        user.roles.append(photographer_role)
        db.session.add(user)
        db.session.commit()
        return user

    def test_valid_token_activates(self, client, pending_user):
        res = client.post(self.ENDPOINT, json={"token": "valid-token-abc"})
        assert res.status_code == 200
        assert res.get_json()["ok"] is True

    def test_expired_token_returns_410(self, client, expired_user):
        res = client.post(self.ENDPOINT, json={"token": "expired-token-xyz"})
        assert res.status_code == 410
        assert res.get_json()["code"] == "token_expired"

    def test_null_timestamp_treated_as_valid(self, client, photographer_role):
        """Users created before the feature (no timestamp) can still activate."""
        user = User(
            email="legacy@test.com",
            active=False,
            activation_pending=True,
            activation_token="legacy-token",
            activation_token_created_at=None,
        )
        user.roles.append(photographer_role)
        db.session.add(user)
        db.session.commit()
        res = client.post(self.ENDPOINT, json={"token": "legacy-token"})
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/auth/resend-activation
# ---------------------------------------------------------------------------


class TestResendActivation:
    ENDPOINT = f"{BASE}/resend-activation"

    @pytest.fixture
    def expired_user(self, photographer_role):
        user = User(
            email="expired@test.com",
            active=False,
            activation_pending=True,
            activation_token="expired-token-xyz",
            activation_token_created_at=datetime.now(timezone.utc)
            - timedelta(hours=73),
        )
        user.set_password("ExpiredPass123!")
        user.roles.append(photographer_role)
        db.session.add(user)
        db.session.commit()
        return user

    @patch("blueprints.api.auth.notify_activation_email")
    def test_resend_generates_new_token(self, mock_mail, client, expired_user):
        res = client.post(self.ENDPOINT, json={"token": "expired-token-xyz"})
        assert res.status_code == 200
        from sqlalchemy import select as sa_select

        user = db.session.execute(
            sa_select(User).where(User.email == "expired@test.com")
        ).scalar_one()
        assert user.activation_token != "expired-token-xyz"
        assert user.activation_token is not None
        assert mock_mail.called

    def test_invalid_token_returns_404(self, client):
        res = client.post(self.ENDPOINT, json={"token": "bogus"})
        assert res.status_code == 404

    def test_missing_token_returns_400(self, client):
        res = client.post(self.ENDPOINT, json={})
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/v1/auth/account
# ---------------------------------------------------------------------------


class TestDeactivateAccount:
    ENDPOINT = f"{BASE}/account"

    @pytest.fixture
    def system_user(self, photographer_role):
        """A system user — must not be able to self-deactivate."""
        user = User(email="system@test.com", active=True, is_system=True)
        user.set_password("SystemPass123!")
        user.roles.append(photographer_role)
        db.session.add(user)
        db.session.commit()
        return user

    def test_unauthenticated_returns_401(self, client):
        res = client.delete(self.ENDPOINT)
        assert res.status_code == 401

    def test_happy_path_returns_200(self, client, photographer_user):
        token = make_token(photographer_user)
        res = client.delete(self.ENDPOINT, headers=auth_header(token))
        assert res.status_code == 200
        assert res.get_json()["ok"] is True

    def test_sets_inactive_and_deleted_at(self, client, photographer_user):
        token = make_token(photographer_user)
        client.delete(self.ENDPOINT, headers=auth_header(token))
        user = db.session.get(User, photographer_user.id)
        assert user.active is False
        assert user.deleted_at is not None

    def test_system_user_returns_403(self, client, system_user):
        token = make_token(system_user)
        res = client.delete(self.ENDPOINT, headers=auth_header(token))
        assert res.status_code == 403

    @patch("blueprints.api.auth.notify_account_cancellation")
    def test_sends_cancellation_email(self, mock_mail, client, photographer_user):
        token = make_token(photographer_user)
        client.delete(self.ENDPOINT, headers=auth_header(token))
        mock_mail.assert_called_once_with(photographer_user.email)

    @patch(
        "blueprints.api.auth.notify_account_cancellation",
        side_effect=Exception("SMTP down"),
    )
    def test_email_failure_does_not_fail_request(
        self, mock_mail, client, photographer_user
    ):
        token = make_token(photographer_user)
        res = client.delete(self.ENDPOINT, headers=auth_header(token))
        assert res.status_code == 200

    def test_token_invalid_after_deactivation(self, client, photographer_user):
        """The same JWT must be rejected immediately after deactivation."""
        token = make_token(photographer_user)
        client.delete(self.ENDPOINT, headers=auth_header(token))
        res = client.get(f"{BASE}/me", headers=auth_header(token))
        assert res.status_code == 401


# POST /api/v1/auth/register — admin notification
# ---------------------------------------------------------------------------


class TestRegisterAdminNotification:
    ENDPOINT = f"{BASE}/register"

    @patch("blueprints.api.auth.notify_admin_new_account")
    @patch("blueprints.api.auth.notify_activation_email")
    def test_register_sends_admin_notification(
        self, mock_activation, mock_admin, client, photographer_role
    ):
        res = client.post(
            self.ENDPOINT,
            json={
                "email": "newuser@test.com",
                "password": "SecurePass123!",
                "agb_accepted": True,
            },
        )
        assert res.status_code == 201
        mock_admin.assert_called_once_with("newuser@test.com", "E-Mail / Passwort")

    @patch("blueprints.api.auth.notify_admin_new_account")
    @patch("blueprints.api.auth.notify_activation_email")
    def test_register_no_admin_notification_on_failure(
        self, mock_activation, mock_admin, client, photographer_role
    ):
        # Missing agb_accepted — registration should fail, no notification sent
        res = client.post(
            self.ENDPOINT,
            json={"email": "newuser@test.com", "password": "SecurePass123!"},
        )
        assert res.status_code == 400
        mock_admin.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/v1/auth/google/register — admin notification
# ---------------------------------------------------------------------------


class TestGoogleRegisterAdminNotification:
    ENDPOINT = f"{BASE}/google/register"

    @patch("blueprints.api.auth.notify_admin_new_account")
    @patch("blueprints.api.auth.notify_activation_email")
    @patch("blueprints.api.auth._google_jwks")
    def test_google_register_sends_admin_notification(
        self, mock_jwks, mock_activation, mock_admin, client, photographer_role
    ):
        google_email = "googleuser2@test.com"
        google_sub = "google-sub-12345"

        mock_signing_key = MagicMock()
        mock_jwks.get_signing_key_from_jwt.return_value = mock_signing_key

        with patch("blueprints.api.auth.jwt.decode") as mock_decode:
            mock_decode.return_value = {"email": google_email, "sub": google_sub}
            with patch(
                "blueprints.api.auth.GOOGLE_FRONTEND_CLIENT_ID", "test-client-id"
            ):
                res = client.post(
                    self.ENDPOINT,
                    json={"credential": "fake-credential", "agb_accepted": True},
                )

        assert res.status_code == 201
        mock_admin.assert_called_once_with(google_email, "Google")
