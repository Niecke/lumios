"""Tests for POST /api/v1/libraries/<id>/videos/init — quota boundaries."""

from unittest.mock import PropertyMock, patch

import pytest

from models import db, User, Role, Library, Image
from services.token import create_token

SIZE = 5000


@pytest.fixture
def photographer():
    role = Role(name="photographer", description="Photographer")
    user = User(email="photo@test.com", active=True)
    user.set_password("PhotoPass123!")
    user.roles.append(role)
    db.session.add_all([role, user])
    db.session.commit()
    return user


@pytest.fixture
def library(photographer):
    lib = Library(user_id=photographer.id, name="Video Library")
    db.session.add(lib)
    db.session.commit()
    return lib


@pytest.fixture(autouse=True)
def video_enabled():
    with patch("blueprints.api.videos.VIDEO_UPLOADS_ENABLED", True), patch(
        "services.videos.storage"
    ) as st:
        st.create_presigned_put_url.return_value = "http://example.com/put"
        yield


def _limits(storage=None, media=5000):
    return {
        "max_libraries": 10,
        "max_images_per_library": media,
        "max_storage_bytes": storage if storage is not None else 10**9,
    }


def _patch_limits(**kwargs):
    return patch.object(
        User, "effective_limits", new_callable=PropertyMock, return_value=_limits(**kwargs)
    )


def _add_media(library, count, size=1000):
    for i in range(count):
        db.session.add(
            Image(
                library_id=library.id,
                s3_key=f"v-{i}.jpg",
                original_filename=f"v-{i}.jpg",
                content_type="image/jpeg",
                size=size,
            )
        )
    db.session.commit()


def _post(client, user, library):
    token = create_token(user.id, user.email, [r.name for r in user.roles])
    return client.post(
        f"/api/v1/libraries/{library.id}/videos/init",
        json={"filename": "v.mp4", "content_type": "video/mp4", "size": SIZE},
        headers={"Authorization": f"Bearer {token}"},
    )


class TestVideoInitQuotas:
    def test_media_count_below_limit_allowed(self, client, photographer, library):
        _add_media(library, 2)
        with _patch_limits(media=3):
            assert _post(client, photographer, library).status_code == 201

    def test_media_count_at_limit_rejected(self, client, photographer, library):
        _add_media(library, 3)
        with _patch_limits(media=3):
            assert _post(client, photographer, library).status_code == 422

    def test_storage_exactly_at_limit_allowed(self, client, photographer, library):
        _add_media(library, 1)
        with _patch_limits(storage=1000 + SIZE):
            assert _post(client, photographer, library).status_code == 201

    def test_storage_one_byte_over_rejected(self, client, photographer, library):
        _add_media(library, 1)
        with _patch_limits(storage=1000 + SIZE - 1):
            assert _post(client, photographer, library).status_code == 422

    def test_storage_overshoot_rejected(self, client, photographer, library):
        _add_media(library, 1)
        with _patch_limits(storage=1000 + SIZE // 2):
            res = _post(client, photographer, library)
        assert res.status_code == 422
        assert res.get_json()["error"].endswith("for your subscription.")
