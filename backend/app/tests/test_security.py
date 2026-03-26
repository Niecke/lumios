"""
Tests for security decorators (login_required, require_role) and
the CurrentUser proxy.
"""

import pytest
from html import unescape
from conftest import do_login, do_logout
from models import db, User, Role
from current_user import CurrentUser


# ---------------------------------------------------------------------------
# login_required decorator (tested via routes that use it)
# ---------------------------------------------------------------------------


class TestLoginRequired:
    """Verify every login_required route redirects unauthenticated visitors."""

    PROTECTED_ROUTES = [
        ("GET", "/"),
        ("GET", "/admin/users"),
        ("GET", "/admin/user_create"),
        ("POST", "/admin/user_create"),
        ("POST", "/admin/user_delete/1"),
        ("GET", "/admin/user_edit/1"),
    ]

    @pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
    def test_redirects_to_login_when_not_authenticated(self, client, method, path):
        if method == "GET":
            response = client.get(path, follow_redirects=False)
        else:
            response = client.post(path, follow_redirects=False)

        assert response.status_code == 302
        assert "/login" in response.location

    def test_redirects_to_login_when_user_is_deactivated(self, client, app):
        """A user whose active flag is cleared mid-session is rejected immediately."""
        user = User(email="deactivated@test.com", active=True)
        user.set_password("DeactPass1!")
        db.session.add(user)
        db.session.commit()

        do_login(client, "deactivated@test.com", "DeactPass1!")

        # Deactivate the user while the session is still live
        user.active = False
        db.session.commit()

        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location


# ---------------------------------------------------------------------------
# require_role decorator (tested via admin routes)
# ---------------------------------------------------------------------------


class TestRequireRole:
    def test_admin_route_shows_role_error_for_regular_user(self, client, regular_user):
        do_login(client, "user@test.com", "UserPass123!")
        response = client.get("/admin/users", follow_redirects=True)
        html = unescape(response.data.decode())
        assert "Access denied." in html

    def test_admin_route_redirects_to_index_for_regular_user(
        self, client, regular_user
    ):
        do_login(client, "user@test.com", "UserPass123!")
        response = client.get("/admin/users", follow_redirects=False)
        assert response.status_code == 302

    def test_admin_route_accessible_with_admin_role(self, client, admin_user):
        do_login(client, "admin@test.com", "AdminPass123!")
        response = client.get("/admin/users")
        assert response.status_code == 200

    def test_unauthenticated_user_gets_login_redirect_not_role_error(self, client):
        # Without a session the login_required decorator fires before require_role
        response = client.get("/admin/users", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location


# ---------------------------------------------------------------------------
# CurrentUser proxy
# ---------------------------------------------------------------------------


class TestCurrentUser:
    def _make_proxy(self, app, user):
        """Return a CurrentUser proxy pre-loaded with *user* inside an app context."""
        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(user)
            yield proxy

    def test_is_authenticated_true_for_active_user(self, app):
        user = User(email="cu_active@test.com", active=True)
        user.set_password("CuActive1!")
        db.session.add(user)
        db.session.commit()

        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(user)
            assert proxy.is_authenticated is True

    def test_is_authenticated_false_for_inactive_user(self, app):
        user = User(email="cu_inactive@test.com", active=False)
        user.set_password("CuInactive1!")
        db.session.add(user)
        db.session.commit()

        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(user)
            assert proxy.is_authenticated is False

    def test_is_anonymous_when_no_user(self, app):
        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(None)
            assert proxy.is_anonymous is True

    def test_is_anonymous_false_for_authenticated_user(self, app):
        user = User(email="cu_anon@test.com", active=True)
        user.set_password("CuAnon123!")
        db.session.add(user)
        db.session.commit()

        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(user)
            assert proxy.is_anonymous is False

    def test_id_returns_user_id(self, app):
        user = User(email="cu_id@test.com", active=True)
        user.set_password("CuId1234!!")
        db.session.add(user)
        db.session.commit()

        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(user)
            assert proxy.id == user.id

    def test_id_returns_none_when_no_user(self, app):
        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(None)
            assert proxy.id is None

    def test_email_returns_user_email(self, app):
        user = User(email="cu_email@test.com", active=True)
        user.set_password("CuEmail1!!")
        db.session.add(user)
        db.session.commit()

        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(user)
            assert proxy.email == "cu_email@test.com"

    def test_email_returns_empty_string_when_no_user(self, app):
        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(None)
            assert proxy.email == ""

    def test_has_role_true(self, app):
        role = Role(name="checker", description="Checker")
        user = User(email="cu_role@test.com", active=True)
        user.set_password("CuRole123!")
        user.roles.append(role)
        db.session.add(user)
        db.session.commit()

        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(user)
            assert proxy.has_role("checker") is True

    def test_has_role_false_for_missing_role(self, app):
        user = User(email="cu_norole@test.com", active=True)
        user.set_password("CuNoRole1!")
        db.session.add(user)
        db.session.commit()

        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(user)
            assert proxy.has_role("nonexistent") is False

    def test_has_role_false_when_no_user(self, app):
        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(None)
            assert proxy.has_role("admin") is False

    def test_roles_empty_list_when_no_user(self, app):
        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(None)
            assert proxy.roles == []

    def test_roles_returns_assigned_roles(self, app):
        role = Role(name="inspector")
        user = User(email="cu_roles@test.com", active=True)
        user.set_password("CuRoles1!!")
        user.roles.append(role)
        db.session.add(user)
        db.session.commit()

        proxy = CurrentUser()
        with app.test_request_context():
            proxy.set_user(user)
            assert len(proxy.roles) == 1
            assert proxy.roles[0].name == "inspector"
