"""
Tests for the JSON API libraries endpoints: /api/v1/libraries/*

Coverage targets:
  GET    /api/v1/libraries           list photographer's libraries
  POST   /api/v1/libraries           create library
  PATCH  /api/v1/libraries/<id>      rename library
  DELETE /api/v1/libraries/<id>      soft-delete library
"""

import pytest

from models import db, User, Role, Library, SubscriptionType
from services.token import create_token

BASE = "/api/v1/libraries"


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
    user = User(
        email="photo@test.com", active=True, max_libraries=5,
        subscription=SubscriptionType.premium,
    )
    user.set_password("PhotoPass123!")
    user.roles.append(photographer_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def other_photographer(photographer_role):
    user = User(
        email="other@test.com", active=True, max_libraries=5,
        subscription=SubscriptionType.premium,
    )
    user.set_password("OtherPass123!")
    user.roles.append(photographer_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def library(photographer):
    lib = Library(user_id=photographer.id, name="Wedding 2025")
    db.session.add(lib)
    db.session.commit()
    return lib


# ---------------------------------------------------------------------------
# GET /api/v1/libraries
# ---------------------------------------------------------------------------


class TestListLibraries:
    def test_returns_200_for_photographer(self, client, photographer):
        token = make_token(photographer)
        res = client.get(BASE, headers=auth_header(token))
        assert res.status_code == 200

    def test_returns_empty_list_when_no_libraries(self, client, photographer):
        token = make_token(photographer)
        res = client.get(BASE, headers=auth_header(token))
        data = res.get_json()
        assert data["libraries"] == []
        assert data["count"] == 0

    def test_returns_existing_libraries(self, client, photographer, library):
        token = make_token(photographer)
        res = client.get(BASE, headers=auth_header(token))
        data = res.get_json()
        assert data["count"] == 1
        assert data["libraries"][0]["name"] == "Wedding 2025"

    def test_returns_max_libraries(self, client, photographer):
        token = make_token(photographer)
        res = client.get(BASE, headers=auth_header(token))
        assert res.get_json()["max_libraries"] == 5

    def test_does_not_return_deleted_libraries(self, client, photographer, library):
        from datetime import datetime, timezone

        library.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        token = make_token(photographer)
        res = client.get(BASE, headers=auth_header(token))
        assert res.get_json()["count"] == 0

    def test_does_not_return_other_photographers_libraries(
        self, client, photographer, other_photographer
    ):
        lib = Library(user_id=other_photographer.id, name="Other Library")
        db.session.add(lib)
        db.session.commit()
        token = make_token(photographer)
        res = client.get(BASE, headers=auth_header(token))
        assert res.get_json()["count"] == 0

    def test_no_auth_returns_401(self, client):
        res = client.get(BASE)
        assert res.status_code == 401

    def test_non_photographer_returns_403(self, client, regular_user):
        token = make_token(regular_user)
        res = client.get(BASE, headers=auth_header(token))
        assert res.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/libraries
# ---------------------------------------------------------------------------


class TestCreateLibrary:
    def test_creates_library_and_returns_201(self, client, photographer):
        token = make_token(photographer)
        res = client.post(
            BASE, json={"name": "Summer Shoot"}, headers=auth_header(token)
        )
        assert res.status_code == 201

    def test_response_contains_id_uuid_name(self, client, photographer):
        token = make_token(photographer)
        res = client.post(
            BASE, json={"name": "Summer Shoot"}, headers=auth_header(token)
        )
        data = res.get_json()
        assert data["name"] == "Summer Shoot"
        assert "id" in data
        assert "uuid" in data

    def test_missing_name_returns_400(self, client, photographer):
        token = make_token(photographer)
        res = client.post(BASE, json={}, headers=auth_header(token))
        assert res.status_code == 400

    def test_empty_name_returns_400(self, client, photographer):
        token = make_token(photographer)
        res = client.post(BASE, json={"name": "   "}, headers=auth_header(token))
        assert res.status_code == 400

    def test_name_too_long_returns_400(self, client, photographer):
        token = make_token(photographer)
        res = client.post(BASE, json={"name": "x" * 256}, headers=auth_header(token))
        assert res.status_code == 400

    def test_library_limit_returns_422(self, client, photographer):
        token = make_token(photographer)
        # Fill up to max_libraries (5)
        for i in range(5):
            client.post(BASE, json={"name": f"Lib {i}"}, headers=auth_header(token))
        res = client.post(
            BASE, json={"name": "One Too Many"}, headers=auth_header(token)
        )
        assert res.status_code == 422

    def test_deleted_libraries_do_not_count_toward_limit(self, client, photographer):
        token = make_token(photographer)
        for i in range(5):
            r = client.post(BASE, json={"name": f"Lib {i}"}, headers=auth_header(token))
            lib_id = r.get_json()["id"]
        # Delete one
        client.delete(f"{BASE}/{lib_id}", headers=auth_header(token))
        # Should now be able to create again
        res = client.post(BASE, json={"name": "New Lib"}, headers=auth_header(token))
        assert res.status_code == 201

    def test_no_auth_returns_401(self, client):
        res = client.post(BASE, json={"name": "Test"})
        assert res.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /api/v1/libraries/<id>
# ---------------------------------------------------------------------------


class TestRenameLibrary:
    def test_renames_library_and_returns_200(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(
            f"{BASE}/{library.id}", json={"name": "Renamed"}, headers=auth_header(token)
        )
        assert res.status_code == 200
        assert res.get_json()["name"] == "Renamed"

    def test_empty_body_returns_200_no_op(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(f"{BASE}/{library.id}", json={}, headers=auth_header(token))
        assert res.status_code == 200

    def test_empty_name_returns_400(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(f"{BASE}/{library.id}", json={"name": "  "}, headers=auth_header(token))
        assert res.status_code == 400

    def test_toggle_use_original_as_preview(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(
            f"{BASE}/{library.id}",
            json={"use_original_as_preview": True},
            headers=auth_header(token),
        )
        assert res.status_code == 200
        assert res.get_json()["use_original_as_preview"] is True

    def test_invalid_use_original_as_preview_returns_400(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(
            f"{BASE}/{library.id}",
            json={"use_original_as_preview": "yes"},
            headers=auth_header(token),
        )
        assert res.status_code == 400

    def test_other_photographers_library_returns_404(
        self, client, other_photographer, library
    ):
        token = make_token(other_photographer)
        res = client.patch(
            f"{BASE}/{library.id}", json={"name": "Hack"}, headers=auth_header(token)
        )
        assert res.status_code == 404

    def test_deleted_library_returns_404(self, client, photographer, library):
        from datetime import datetime, timezone

        library.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        token = make_token(photographer)
        res = client.patch(
            f"{BASE}/{library.id}", json={"name": "Renamed"}, headers=auth_header(token)
        )
        assert res.status_code == 404

    def test_no_auth_returns_401(self, client, library):
        res = client.patch(f"{BASE}/{library.id}", json={"name": "X"})
        assert res.status_code == 401

    def test_set_is_private_true_returns_200(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(
            f"{BASE}/{library.id}",
            json={"is_private": True},
            headers=auth_header(token),
        )
        assert res.status_code == 200
        assert res.get_json()["is_private"] is True

    def test_set_is_private_false_returns_200(self, client, photographer, library):
        library.is_private = True
        from models import db
        db.session.commit()
        token = make_token(photographer)
        res = client.patch(
            f"{BASE}/{library.id}",
            json={"is_private": False},
            headers=auth_header(token),
        )
        assert res.status_code == 200
        assert res.get_json()["is_private"] is False

    def test_invalid_is_private_returns_400(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(
            f"{BASE}/{library.id}",
            json={"is_private": "yes"},
            headers=auth_header(token),
        )
        assert res.status_code == 400

    def test_is_private_returned_in_library_list(self, client, photographer, library):
        token = make_token(photographer)
        res = client.get(BASE, headers=auth_header(token))
        data = res.get_json()
        assert "is_private" in data["libraries"][0]


# ---------------------------------------------------------------------------
# DELETE /api/v1/libraries/<id>
# ---------------------------------------------------------------------------


class TestDeleteLibrary:
    def test_soft_deletes_library_and_returns_204(self, client, photographer, library):
        token = make_token(photographer)
        res = client.delete(f"{BASE}/{library.id}", headers=auth_header(token))
        assert res.status_code == 204

    def test_deleted_library_disappears_from_list(self, client, photographer, library):
        token = make_token(photographer)
        client.delete(f"{BASE}/{library.id}", headers=auth_header(token))
        res = client.get(BASE, headers=auth_header(token))
        assert res.get_json()["count"] == 0

    def test_deleted_at_is_set_in_db(self, client, photographer, library):
        token = make_token(photographer)
        client.delete(f"{BASE}/{library.id}", headers=auth_header(token))
        db.session.refresh(library)
        assert library.deleted_at is not None

    def test_other_photographers_library_returns_404(
        self, client, other_photographer, library
    ):
        token = make_token(other_photographer)
        res = client.delete(f"{BASE}/{library.id}", headers=auth_header(token))
        assert res.status_code == 404

    def test_already_deleted_returns_404(self, client, photographer, library):
        from datetime import datetime, timezone

        library.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        token = make_token(photographer)
        res = client.delete(f"{BASE}/{library.id}", headers=auth_header(token))
        assert res.status_code == 404

    def test_no_auth_returns_401(self, client, library):
        res = client.delete(f"{BASE}/{library.id}")
        assert res.status_code == 401
