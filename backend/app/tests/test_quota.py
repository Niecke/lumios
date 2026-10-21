"""Unit tests for services.quota.check_upload_allowed."""

from datetime import datetime, timezone
from unittest.mock import PropertyMock, patch

import pytest

from models import db, User, Library, Image, Video
from services.quota import check_upload_allowed

STORAGE_LIMIT = 10_000
MEDIA_LIMIT = 3


@pytest.fixture
def owner(app):
    user = User(email="quota@test.com", active=True)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def library(owner):
    lib = Library(user_id=owner.id, name="Quota Library")
    db.session.add(lib)
    db.session.commit()
    return lib


@pytest.fixture(autouse=True)
def small_limits(app):
    limits = {
        "max_libraries": 10,
        "max_images_per_library": MEDIA_LIMIT,
        "max_storage_bytes": STORAGE_LIMIT,
    }
    with patch.object(
        User, "effective_limits", new_callable=PropertyMock, return_value=limits
    ):
        yield


def add_image(library, size, deleted=False):
    db.session.add(
        Image(
            library_id=library.id,
            s3_key="k.jpg",
            original_filename="k.jpg",
            content_type="image/jpeg",
            size=size,
            deleted_at=datetime.now(timezone.utc) if deleted else None,
        )
    )
    db.session.commit()


def add_video(library, size, deleted=False):
    db.session.add(
        Video(
            library_id=library.id,
            s3_key="k.mp4",
            original_filename="k.mp4",
            content_type="video/mp4",
            size=size,
            deleted_at=datetime.now(timezone.utc) if deleted else None,
        )
    )
    db.session.commit()


class TestStorageLimit:
    def test_empty_library_allowed(self, owner, library):
        assert check_upload_allowed(owner, library, 100) is None

    def test_exactly_at_limit_allowed(self, owner, library):
        add_image(library, 4000)
        add_video(library, 1000)
        assert check_upload_allowed(owner, library, STORAGE_LIMIT - 5000) is None

    def test_one_byte_over_rejected(self, owner, library):
        add_image(library, 4000)
        add_video(library, 1000)
        res, status = check_upload_allowed(owner, library, STORAGE_LIMIT - 5000 + 1)
        assert status == 422

    def test_overshoot_below_limit_rejected(self, owner, library):
        add_image(library, 9000)
        res, status = check_upload_allowed(owner, library, 5000)
        assert status == 422

    def test_message_for_photographer(self, owner, library):
        res, _ = check_upload_allowed(owner, library, STORAGE_LIMIT + 1)
        assert res.get_json()["error"] == "Storage limit reached (0 MB) for your subscription."

    def test_message_for_external(self, owner, library):
        res, _ = check_upload_allowed(owner, library, STORAGE_LIMIT + 1, is_external=True)
        assert res.get_json()["error"] == "Storage limit reached (0 MB) for this library."

    def test_storage_sums_across_libraries(self, owner, library):
        other = Library(user_id=owner.id, name="Other")
        db.session.add(other)
        db.session.commit()
        add_image(other, STORAGE_LIMIT)
        _, status = check_upload_allowed(owner, library, 1)
        assert status == 422

    def test_other_users_storage_ignored(self, owner, library):
        stranger = User(email="stranger@test.com", active=True)
        db.session.add(stranger)
        db.session.commit()
        lib = Library(user_id=stranger.id, name="Stranger")
        db.session.add(lib)
        db.session.commit()
        add_image(lib, STORAGE_LIMIT)
        assert check_upload_allowed(owner, library, STORAGE_LIMIT) is None


class TestMediaLimit:
    def test_below_limit_allowed(self, owner, library):
        add_image(library, 1)
        add_video(library, 1)
        assert check_upload_allowed(owner, library, 1) is None

    def test_at_limit_rejected(self, owner, library):
        add_image(library, 1)
        add_image(library, 1)
        add_video(library, 1)
        res, status = check_upload_allowed(owner, library, 1)
        assert status == 422
        assert res.get_json()["error"] == f"Media limit reached ({MEDIA_LIMIT}) for this library."

    def test_media_limit_is_per_library(self, owner, library):
        other = Library(user_id=owner.id, name="Other")
        db.session.add(other)
        db.session.commit()
        for _ in range(MEDIA_LIMIT):
            add_image(other, 1)
        assert check_upload_allowed(owner, library, 1) is None


class TestSoftDeletes:
    def test_deleted_media_not_counted(self, owner, library):
        add_image(library, 4000, deleted=True)
        add_video(library, 4000, deleted=True)
        add_image(library, 1)
        add_image(library, 1)
        assert check_upload_allowed(owner, library, STORAGE_LIMIT - 2) is None

    def test_media_in_deleted_library_not_in_storage(self, owner, library):
        gone = Library(
            user_id=owner.id, name="Gone", deleted_at=datetime.now(timezone.utc)
        )
        db.session.add(gone)
        db.session.commit()
        add_image(gone, STORAGE_LIMIT)
        add_video(gone, STORAGE_LIMIT)
        assert check_upload_allowed(owner, library, STORAGE_LIMIT) is None
