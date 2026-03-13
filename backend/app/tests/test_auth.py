"""
Tests for authentication routes: /login, /logout, and the protected index /.
"""
import pytest
from conftest import do_login, do_logout


class TestLoginPage:
    def test_get_login_returns_200(self, client):
        response = client.get("/login")
        assert response.status_code == 200

    def test_get_login_contains_form(self, client):
        response = client.get("/login")
        html = response.data.decode()
        assert "email" in html.lower()
        assert "password" in html.lower()


class TestLoginPost:
    def test_valid_credentials_redirect_to_index(self, client, regular_user):
        response = client.post(
            "/login",
            data={"email": "user@test.com", "password": "UserPass123!"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.location.endswith("/")

    def test_valid_credentials_follow_redirect_shows_index(self, client, regular_user):
        response = do_login(client, "user@test.com", "UserPass123!")
        assert response.status_code == 200

    def test_wrong_password_stays_on_login(self, client, regular_user):
        response = do_login(client, "user@test.com", "WrongPassword!")
        assert response.status_code == 200
        html = response.data.decode()
        assert "Invalid email or password" in html

    def test_nonexistent_email_shows_error(self, client):
        response = do_login(client, "ghost@test.com", "SomePassword1!")
        assert response.status_code == 200
        html = response.data.decode()
        assert "Invalid email or password" in html

    def test_inactive_user_cannot_login(self, client, inactive_user):
        response = do_login(client, "inactive@test.com", "InactivePass123!")
        assert response.status_code == 200
        html = response.data.decode()
        assert "Invalid email or password" in html

    def test_inactive_user_has_no_session_after_login_attempt(self, client, inactive_user):
        client.post(
            "/login",
            data={"email": "inactive@test.com", "password": "InactivePass123!"},
        )
        with client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_empty_email_and_password(self, client):
        response = do_login(client, "", "")
        assert response.status_code == 200
        html = response.data.decode()
        assert "Invalid email or password" in html

    def test_session_contains_user_id_after_login(self, client, regular_user):
        with client.session_transaction() as sess:
            assert "user_id" not in sess

        client.post(
            "/login",
            data={"email": "user@test.com", "password": "UserPass123!"},
        )

        with client.session_transaction() as sess:
            assert sess.get("user_id") == regular_user.id

    def test_session_contains_email_after_login(self, client, regular_user):
        client.post(
            "/login",
            data={"email": "user@test.com", "password": "UserPass123!"},
        )
        with client.session_transaction() as sess:
            assert sess.get("email") == "user@test.com"

    def test_admin_user_can_login(self, client, admin_user):
        response = do_login(client, "admin@test.com", "AdminPass123!")
        assert response.status_code == 200

    def test_login_already_authenticated_user(self, client, regular_user):
        # Logging in a second time should still work (session is cleared then reset)
        do_login(client, "user@test.com", "UserPass123!")
        response = do_login(client, "user@test.com", "UserPass123!")
        assert response.status_code == 200


class TestLogout:
    def test_logout_clears_session(self, client, regular_user):
        do_login(client, "user@test.com", "UserPass123!")

        with client.session_transaction() as sess:
            assert "user_id" in sess

        do_logout(client)

        with client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_logout_redirects_to_index(self, client, regular_user):
        do_login(client, "user@test.com", "UserPass123!")
        response = client.post("/logout", follow_redirects=False)
        assert response.status_code == 302

    def test_logout_shows_success_message(self, client, regular_user):
        do_login(client, "user@test.com", "UserPass123!")
        response = do_logout(client)
        html = response.data.decode()
        assert "Logged out successfully" in html

    def test_logout_when_not_logged_in(self, client):
        # Logout without being logged in should not crash
        response = client.post("/logout", follow_redirects=True)
        assert response.status_code == 200

    def test_logout_requires_post(self, client):
        # GET /logout should not be a valid route
        response = client.get("/logout")
        assert response.status_code == 405


class TestIndexRoute:
    def test_index_redirects_unauthenticated(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location

    def test_index_accessible_when_logged_in(self, client, admin_user):
        do_login(client, "admin@test.com", "AdminPass123!")
        response = client.get("/")
        assert response.status_code == 200

    def test_index_after_logout_redirects_again(self, client, regular_user):
        do_login(client, "user@test.com", "UserPass123!")
        do_logout(client)
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location
