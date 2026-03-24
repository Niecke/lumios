"""
Tests for the support ticket API: /api/v1/support/tickets/*
and the admin support routes: /admin/support/*
"""

import pytest
from models import db, User, Role, SupportTicket, SupportTicketStatus, SupportTicketComment
from services.token import create_token
from conftest import do_login

BASE = "/api/v1/support/tickets"


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
def other_photographer(photographer_role):
    user = User(email="other@test.com", active=True)
    user.set_password("OtherPass123!")
    user.roles.append(photographer_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def ticket(photographer):
    t = SupportTicket(
        user_id=photographer.id,
        subject="Test subject",
        body="Test body content",
    )
    db.session.add(t)
    db.session.commit()
    return t


# ---------------------------------------------------------------------------
# GET /api/v1/support/tickets — list
# ---------------------------------------------------------------------------


class TestListTickets:
    def test_requires_auth(self, client):
        res = client.get(BASE)
        assert res.status_code == 401

    def test_returns_own_tickets(self, client, photographer, ticket):
        res = client.get(BASE, headers=auth_header(make_token(photographer)))
        assert res.status_code == 200
        data = res.get_json()
        assert len(data["tickets"]) == 1
        assert data["tickets"][0]["subject"] == "Test subject"

    def test_does_not_return_other_users_tickets(self, client, photographer, other_photographer, ticket):
        res = client.get(BASE, headers=auth_header(make_token(other_photographer)))
        assert res.status_code == 200
        assert res.get_json()["tickets"] == []

    def test_includes_comments(self, client, photographer, ticket):
        comment = SupportTicketComment(ticket_id=ticket.id, body="Admin reply")
        db.session.add(comment)
        db.session.commit()

        res = client.get(BASE, headers=auth_header(make_token(photographer)))
        assert res.status_code == 200
        first = res.get_json()["tickets"][0]
        assert len(first["comments"]) == 1
        assert first["comments"][0]["body"] == "Admin reply"


# ---------------------------------------------------------------------------
# POST /api/v1/support/tickets — create
# ---------------------------------------------------------------------------


class TestCreateTicket:
    def test_requires_auth(self, client):
        res = client.post(BASE, json={"subject": "S", "body": "B"})
        assert res.status_code == 401

    def test_creates_ticket(self, client, photographer):
        res = client.post(
            BASE,
            json={"subject": "My issue", "body": "Something is broken."},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["subject"] == "My issue"
        assert data["status"] == "open"
        assert data["comments"] == []

    def test_missing_subject_returns_400(self, client, photographer):
        res = client.post(
            BASE,
            json={"body": "No subject here"},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 400
        assert "subject" in res.get_json()["error"]

    def test_missing_body_returns_400(self, client, photographer):
        res = client.post(
            BASE,
            json={"subject": "Subject only"},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 400
        assert "body" in res.get_json()["error"]

    def test_subject_too_long_returns_400(self, client, photographer):
        res = client.post(
            BASE,
            json={"subject": "x" * 256, "body": "Body"},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 400

    def test_open_ticket_limit_enforced(self, client, photographer):
        # Create 100 open tickets directly in the DB
        for i in range(100):
            db.session.add(SupportTicket(
                user_id=photographer.id,
                subject=f"Ticket {i}",
                body="body",
            ))
        db.session.commit()

        res = client.post(
            BASE,
            json={"subject": "Over limit", "body": "Should be blocked"},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 429

    def test_closed_tickets_not_counted_toward_limit(self, client, photographer):
        # 100 closed tickets — should not block creation
        for i in range(100):
            t = SupportTicket(
                user_id=photographer.id,
                subject=f"Ticket {i}",
                body="body",
                status=SupportTicketStatus.closed,
            )
            db.session.add(t)
        db.session.commit()

        res = client.post(
            BASE,
            json={"subject": "New open ticket", "body": "Should succeed"},
            headers=auth_header(make_token(photographer)),
        )
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# GET /api/v1/support/tickets/<id> — detail
# ---------------------------------------------------------------------------


class TestGetTicket:
    def test_requires_auth(self, client, ticket):
        res = client.get(f"{BASE}/{ticket.id}")
        assert res.status_code == 401

    def test_returns_own_ticket(self, client, photographer, ticket):
        res = client.get(f"{BASE}/{ticket.id}", headers=auth_header(make_token(photographer)))
        assert res.status_code == 200
        assert res.get_json()["id"] == ticket.id

    def test_cannot_access_other_users_ticket(self, client, other_photographer, ticket):
        res = client.get(f"{BASE}/{ticket.id}", headers=auth_header(make_token(other_photographer)))
        assert res.status_code == 404

    def test_unknown_ticket_returns_404(self, client, photographer):
        res = client.get(f"{BASE}/99999", headers=auth_header(make_token(photographer)))
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


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


class TestAdminSupportList:
    def test_requires_login(self, client):
        res = client.get("/admin/support", follow_redirects=False)
        assert res.status_code == 302
        assert "/login" in res.location

    def test_requires_admin_role(self, client, photographer):
        do_login(client, "photo@test.com", "PhotoPass123!")
        res = client.get("/admin/support", follow_redirects=True)
        assert "Access denied." in res.data.decode()

    def test_shows_all_tickets(self, client, admin_user, photographer, ticket):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.get("/admin/support")
        assert res.status_code == 200
        assert "Test subject" in res.data.decode()


class TestAdminSupportDetail:
    def test_shows_ticket(self, client, admin_user, photographer, ticket):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.get(f"/admin/support/{ticket.id}")
        assert res.status_code == 200
        assert "Test subject" in res.data.decode()
        assert "Test body content" in res.data.decode()

    def test_unknown_ticket_redirects(self, client, admin_user):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.get("/admin/support/99999", follow_redirects=True)
        assert "Ticket not found." in res.data.decode()


class TestAdminSupportComment:
    def test_add_comment(self, client, admin_user, photographer, ticket):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.post(
            f"/admin/support/{ticket.id}/comment",
            data={"body": "We are looking into it."},
            follow_redirects=True,
        )
        assert res.status_code == 200
        assert "Comment added." in res.data.decode()

        db.session.refresh(ticket)
        assert len(ticket.comments) == 1
        assert ticket.comments[0].body == "We are looking into it."
        assert ticket.status == SupportTicketStatus.open

    def test_add_comment_and_close(self, client, admin_user, photographer, ticket):
        do_login(client, "admin@test.com", "AdminPass123!")
        client.post(
            f"/admin/support/{ticket.id}/comment",
            data={"body": "Fixed!", "close": "on"},
            follow_redirects=True,
        )
        db.session.refresh(ticket)
        assert ticket.status == SupportTicketStatus.closed
        assert len(ticket.comments) == 1

    def test_empty_body_rejected(self, client, admin_user, photographer, ticket):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.post(
            f"/admin/support/{ticket.id}/comment",
            data={"body": "   "},
            follow_redirects=True,
        )
        assert "Comment body is required." in res.data.decode()


class TestAdminSupportClose:
    def test_close_ticket(self, client, admin_user, photographer, ticket):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.post(
            f"/admin/support/{ticket.id}/close",
            follow_redirects=True,
        )
        assert res.status_code == 200
        assert "Ticket closed." in res.data.decode()

        db.session.refresh(ticket)
        assert ticket.status == SupportTicketStatus.closed

    def test_requires_post(self, client, admin_user, photographer, ticket):
        do_login(client, "admin@test.com", "AdminPass123!")
        res = client.get(f"/admin/support/{ticket.id}/close")
        assert res.status_code == 405
