"""
Tests for the feedback API: /api/v1/feedback
and the admin feedback routes: /admin/feedback/*
"""

import pytest
from models import db, User, Role, Feedback
from services.token import create_token
from conftest import do_login

BASE = "/api/v1/feedback"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_token(user: User) -> str:
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
def photographer(photographer_role):
    user = User(email="photo@test.com", active=True)
    user.set_password("PhotoPass123!")
    user.roles.append(photographer_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def admin_role():
    role = Role(name="admin", description="Administrator")
    db.session.add(role)
    db.session.commit()
    return role


@pytest.fixture
def admin_user(admin_role):
    user = User(email="admin@test.com", active=True)
    user.set_password("AdminPass123!")
    user.roles.append(admin_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def feedback(photographer):
    fb = Feedback(user_id=photographer.id, rating=4, body="Great app!")
    db.session.add(fb)
    db.session.commit()
    return fb


# ---------------------------------------------------------------------------
# POST /api/v1/feedback — submit
# ---------------------------------------------------------------------------


class TestSubmitFeedback:
    def test_requires_auth(self, client):
        res = client.post(BASE, json={"rating": 5})
        assert res.status_code == 401

    def test_creates_feedback_with_body(self, client, photographer):
        res = client.post(
            BASE,
            json={"rating": 4, "body": "Loving this!"},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["rating"] == 4
        assert data["body"] == "Loving this!"

    def test_creates_feedback_without_body(self, client, photographer):
        res = client.post(
            BASE,
            json={"rating": 5},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["rating"] == 5
        assert data["body"] is None

    def test_missing_rating_returns_400(self, client, photographer):
        res = client.post(
            BASE,
            json={"body": "No rating"},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 400
        assert "rating" in res.get_json()["error"]

    def test_rating_zero_returns_400(self, client, photographer):
        res = client.post(
            BASE,
            json={"rating": 0},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 400

    def test_rating_six_returns_400(self, client, photographer):
        res = client.post(
            BASE,
            json={"rating": 6},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 400

    def test_body_too_long_returns_400(self, client, photographer):
        res = client.post(
            BASE,
            json={"rating": 3, "body": "x" * 2001},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 400

    def test_feedback_limit_enforced(self, client, photographer):
        for i in range(100):
            db.session.add(Feedback(user_id=photographer.id, rating=3))
        db.session.commit()

        res = client.post(
            BASE,
            json={"rating": 5},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 429

    def test_response_does_not_include_admin_note(self, client, photographer):
        res = client.post(
            BASE,
            json={"rating": 5},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 201
        assert "admin_note" not in res.get_json()


# ---------------------------------------------------------------------------
# PATCH /api/v1/feedback/<id>/note — admin note
# ---------------------------------------------------------------------------


class TestSetAdminNote:
    def test_requires_auth(self, client, feedback):
        res = client.patch(f"{BASE}/{feedback.id}/note", json={"note": "test"})
        assert res.status_code == 401

    def test_requires_admin_role(self, client, photographer, feedback):
        res = client.patch(
            f"{BASE}/{feedback.id}/note",
            json={"note": "test"},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 403

    def test_sets_note(self, client, admin_user, feedback):
        res = client.patch(
            f"{BASE}/{feedback.id}/note",
            json={"note": "https://github.com/issues/123"},
            headers=auth_header(make_token(admin_user)),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["admin_note"] == "https://github.com/issues/123"
        db.session.refresh(feedback)
        assert feedback.admin_note == "https://github.com/issues/123"

    def test_clears_note_with_empty_string(self, client, admin_user, feedback):
        feedback.admin_note = "existing note"
        db.session.commit()

        res = client.patch(
            f"{BASE}/{feedback.id}/note",
            json={"note": ""},
            headers=auth_header(make_token(admin_user)),
        )
        assert res.status_code == 200
        db.session.refresh(feedback)
        assert feedback.admin_note is None

    def test_unknown_id_returns_404(self, client, admin_user):
        res = client.patch(
            f"{BASE}/99999/note",
            json={"note": "test"},
            headers=auth_header(make_token(admin_user)),
        )
        assert res.status_code == 404

    def test_note_too_long_returns_400(self, client, admin_user, feedback):
        res = client.patch(
            f"{BASE}/{feedback.id}/note",
            json={"note": "x" * 1001},
            headers=auth_header(make_token(admin_user)),
        )
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


class TestAdminFeedbackList:
    def test_requires_login(self, client):
        res = client.get("/admin/feedback", follow_redirects=False)
        assert res.status_code == 302
        assert "/login" in res.location

    def test_requires_admin_role(self, client, photographer):
        do_login(client, "photo@test.com", "PhotoPass123!")
        res = client.get("/admin/feedback", follow_redirects=True)
        assert "Access denied." in res.data.decode()

    def test_shows_all_feedback(self, client, admin_user, photographer, feedback):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.get("/admin/feedback")
        assert res.status_code == 200
        assert "Great app!" in res.data.decode()


class TestAdminFeedbackNote:
    def test_add_note(self, client, admin_user, photographer, feedback):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.post(
            f"/admin/feedback/{feedback.id}/note",
            data={"note": "GitHub issue #42"},
            follow_redirects=True,
        )
        assert res.status_code == 200
        assert "Note saved." in res.data.decode()
        db.session.refresh(feedback)
        assert feedback.admin_note == "GitHub issue #42"

    def test_clear_note(self, client, admin_user, photographer, feedback):
        feedback.admin_note = "old note"
        db.session.commit()

        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.post(
            f"/admin/feedback/{feedback.id}/note",
            data={"note": ""},
            follow_redirects=True,
        )
        assert res.status_code == 200
        db.session.refresh(feedback)
        assert feedback.admin_note is None

    def test_unknown_id_redirects(self, client, admin_user):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.post(
            "/admin/feedback/99999/note",
            data={"note": "test"},
            follow_redirects=True,
        )
        assert "Feedback not found." in res.data.decode()

    def test_note_too_long_rejected(self, client, admin_user, photographer, feedback):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.post(
            f"/admin/feedback/{feedback.id}/note",
            data={"note": "x" * 1001},
            follow_redirects=True,
        )
        assert "1000 characters" in res.data.decode()
