"""
Tests for the public API endpoints: /api/v1/public/libraries/*

Coverage targets:
  GET   /api/v1/public/libraries/<uuid>                          view library
  PATCH /api/v1/public/libraries/<uuid>/images/<uuid>/state      update customer state
  POST  /api/v1/public/libraries/<uuid>/finish                   finish selection
  GET   /api/v1/public/libraries/<uuid>/images/<uuid>/download   download image

Private library enforcement: all four routes must return 404 when
library.is_private is True.
"""

import pytest
from unittest.mock import patch

from models import db, User, Role, Library, Image, CustomerState, SubscriptionType
from services.token import create_token

BASE = "/api/v1/public"


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
        email="photo@test.com",
        active=True,
        max_libraries=5,
        subscription=SubscriptionType.premium,
    )
    user.set_password("PhotoPass123!")
    user.roles.append(photographer_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def public_library(photographer):
    lib = Library(user_id=photographer.id, name="Public Gallery", is_private=False)
    db.session.add(lib)
    db.session.commit()
    return lib


@pytest.fixture
def private_library(photographer):
    lib = Library(user_id=photographer.id, name="Private Gallery", is_private=True)
    db.session.add(lib)
    db.session.commit()
    return lib


@pytest.fixture
def image_in_library(public_library):
    img = Image(
        library_id=public_library.id,
        s3_key="test-uuid.jpg",
        original_filename="test.jpg",
        content_type="image/jpeg",
        size=1024,
        width=100,
        height=100,
        customer_state=CustomerState.none,
    )
    db.session.add(img)
    db.session.commit()
    return img


# ---------------------------------------------------------------------------
# GET /api/v1/public/libraries/<uuid>
# ---------------------------------------------------------------------------


class TestGetPublicLibrary:
    def test_public_library_returns_200(self, client, public_library):
        with patch("services.storage.get_presigned_url", return_value="http://example.com/img"):
            res = client.get(f"{BASE}/libraries/{public_library.uuid}")
        assert res.status_code == 200

    def test_response_contains_library_data(self, client, public_library):
        with patch("services.storage.get_presigned_url", return_value="http://example.com/img"):
            res = client.get(f"{BASE}/libraries/{public_library.uuid}")
        data = res.get_json()
        assert data["library"]["uuid"] == public_library.uuid
        assert data["library"]["name"] == "Public Gallery"

    def test_private_library_returns_404(self, client, private_library):
        res = client.get(f"{BASE}/libraries/{private_library.uuid}")
        assert res.status_code == 404

    def test_nonexistent_library_returns_404(self, client):
        res = client.get(f"{BASE}/libraries/00000000-0000-0000-0000-000000000000")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/public/libraries/<uuid>/images/<uuid>/state
# ---------------------------------------------------------------------------


class TestUpdateCustomerState:
    def test_valid_state_returns_200(self, client, public_library, image_in_library):
        res = client.patch(
            f"{BASE}/libraries/{public_library.uuid}/images/{image_in_library.uuid}/state",
            json={"customer_state": "liked"},
        )
        assert res.status_code == 200
        assert res.get_json()["customer_state"] == "liked"

    def test_private_library_returns_404(self, client, private_library):
        res = client.patch(
            f"{BASE}/libraries/{private_library.uuid}/images/some-uuid/state",
            json={"customer_state": "liked"},
        )
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/public/libraries/<uuid>/finish
# ---------------------------------------------------------------------------


class TestFinishLibrary:
    def test_private_library_returns_404(self, client, private_library):
        res = client.post(f"{BASE}/libraries/{private_library.uuid}/finish")
        assert res.status_code == 404

    def test_finish_with_liked_image_returns_200(self, client, public_library, image_in_library):
        image_in_library.customer_state = CustomerState.liked
        db.session.commit()
        with patch("services.mail.notify_gallery_finished"):
            res = client.post(f"{BASE}/libraries/{public_library.uuid}/finish")
        assert res.status_code == 200

    def test_finish_without_liked_image_returns_422(self, client, public_library):
        res = client.post(f"{BASE}/libraries/{public_library.uuid}/finish")
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/public/libraries/<uuid>/images/<uuid>/download
# ---------------------------------------------------------------------------


class TestDownloadImage:
    def test_private_library_returns_404(self, client, private_library):
        res = client.get(
            f"{BASE}/libraries/{private_library.uuid}/images/some-uuid/download"
        )
        assert res.status_code == 404

    def test_download_disabled_returns_403(self, client, public_library, image_in_library):
        res = client.get(
            f"{BASE}/libraries/{public_library.uuid}/images/{image_in_library.uuid}/download"
        )
        assert res.status_code == 403

    def test_download_enabled_returns_200(self, client, public_library, image_in_library):
        public_library.download_enabled = True
        db.session.commit()
        with patch(
            "services.storage.get_presigned_download_url",
            return_value="http://example.com/dl",
        ):
            res = client.get(
                f"{BASE}/libraries/{public_library.uuid}/images/{image_in_library.uuid}/download"
            )
        assert res.status_code == 200
        assert res.get_json()["download_url"] == "http://example.com/dl"


# ---------------------------------------------------------------------------
# GET /api/v1/public/libraries/<uuid> — pagination
# ---------------------------------------------------------------------------


def make_images_in_library(library, count):
    for i in range(count):
        db.session.add(
            Image(
                library_id=library.id,
                s3_key=f"pub-img-{i}.jpg",
                original_filename=f"img-{i}.jpg",
                content_type="image/jpeg",
                size=1024,
                width=100,
                height=100,
                customer_state=CustomerState.none,
            )
        )
    db.session.commit()


class TestGetPublicLibraryPagination:
    def test_response_includes_pagination_fields(self, client, public_library):
        with patch("services.storage.get_presigned_url", return_value="http://example.com/img"):
            data = client.get(
                f"{BASE}/libraries/{public_library.uuid}"
            ).get_json()
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "has_more" in data

    def test_library_metadata_present_on_every_page(self, client, public_library):
        make_images_in_library(public_library, 5)
        with patch("services.storage.get_presigned_url", return_value="http://example.com/img"):
            page1 = client.get(
                f"{BASE}/libraries/{public_library.uuid}?page=1&page_size=3"
            ).get_json()
            page2 = client.get(
                f"{BASE}/libraries/{public_library.uuid}?page=2&page_size=3"
            ).get_json()
        assert page1["library"]["uuid"] == public_library.uuid
        assert page2["library"]["uuid"] == public_library.uuid

    def test_has_more_true_when_more_pages_exist(self, client, public_library):
        make_images_in_library(public_library, 5)
        with patch("services.storage.get_presigned_url", return_value="http://example.com/img"):
            data = client.get(
                f"{BASE}/libraries/{public_library.uuid}?page_size=3"
            ).get_json()
        assert data["has_more"] is True
        assert len(data["images"]) == 3

    def test_has_more_false_on_last_page(self, client, public_library):
        make_images_in_library(public_library, 3)
        with patch("services.storage.get_presigned_url", return_value="http://example.com/img"):
            data = client.get(
                f"{BASE}/libraries/{public_library.uuid}?page_size=10"
            ).get_json()
        assert data["has_more"] is False

    def test_view_only_recorded_on_page_1(self, client, public_library):
        make_images_in_library(public_library, 5)
        with patch("services.storage.get_presigned_url", return_value="http://example.com/img"), \
             patch("blueprints.api.public._record_library_view") as mock_record:
            client.get(f"{BASE}/libraries/{public_library.uuid}?page=1&page_size=3")
            client.get(f"{BASE}/libraries/{public_library.uuid}?page=2&page_size=3")
        assert mock_record.call_count == 1


# ---------------------------------------------------------------------------
# POST /api/v1/public/libraries/<uuid>/images  — public upload
# ---------------------------------------------------------------------------


import io as _io
from PIL import Image as _PilImage
from unittest.mock import patch as _patch


def _make_jpeg_bytes() -> bytes:
    buf = _io.BytesIO()
    img = _PilImage.new("RGB", (2, 2), color="blue")
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestPublicUpload:
    @pytest.fixture
    def upload_library(self, photographer):
        lib = Library(
            user_id=photographer.id,
            name="Upload Gallery",
            is_private=False,
            public_upload_enabled=True,
        )
        db.session.add(lib)
        db.session.commit()
        return lib

    @pytest.fixture
    def disabled_library(self, photographer):
        lib = Library(
            user_id=photographer.id,
            name="Disabled Gallery",
            is_private=False,
            public_upload_enabled=False,
        )
        db.session.add(lib)
        db.session.commit()
        return lib

    def _post_jpeg(self, client, library_uuid, data=None):
        jpeg = data or _make_jpeg_bytes()
        return client.post(
            f"{BASE}/libraries/{library_uuid}/images",
            data={"file": (_io.BytesIO(jpeg), "photo.jpg", "image/jpeg")},
            content_type="multipart/form-data",
        )

    def test_upload_disabled_returns_403(self, client, disabled_library):
        with _patch("services.images.storage"):
            res = self._post_jpeg(client, disabled_library.uuid)
        assert res.status_code == 403

    def test_upload_enabled_accepts_jpeg(self, client, upload_library):
        with _patch("services.images.storage"):
            res = self._post_jpeg(client, upload_library.uuid)
        assert res.status_code == 201
        assert "uuid" in res.get_json()

    def test_upload_marks_image_as_external(self, client, upload_library):
        from models import Image as _Image
        from sqlalchemy import select as _select
        with _patch("services.images.storage"):
            self._post_jpeg(client, upload_library.uuid)
        img = db.session.execute(
            _select(_Image).where(_Image.library_id == upload_library.id)
        ).scalar_one_or_none()
        assert img is not None
        assert img.is_external is True

    def test_private_library_returns_404(self, client, private_library):
        private_library.public_upload_enabled = True
        db.session.commit()
        with _patch("services.images.storage"):
            res = self._post_jpeg(client, private_library.uuid)
        assert res.status_code == 404

    def test_upload_rejects_wrong_content_type(self, client, upload_library):
        res = client.post(
            f"{BASE}/libraries/{upload_library.uuid}/images",
            data={"file": (_io.BytesIO(b"hello"), "text.txt", "text/plain")},
            content_type="multipart/form-data",
        )
        assert res.status_code == 415

    def test_public_upload_enforces_quota(self, client, upload_library, photographer):
        photographer.max_images_per_library = 0
        db.session.commit()
        with _patch("services.images.storage"):
            res = self._post_jpeg(client, upload_library.uuid)
        assert res.status_code == 422

    def test_response_contains_public_upload_enabled(self, client, upload_library):
        with _patch("services.storage.get_presigned_url", return_value="http://example.com/img"):
            res = client.get(f"{BASE}/libraries/{upload_library.uuid}")
        data = res.get_json()
        assert "public_upload_enabled" in data["library"]
        assert data["library"]["public_upload_enabled"] is True

    def test_response_public_upload_enabled_defaults_false(self, client, public_library):
        with _patch("services.storage.get_presigned_url", return_value="http://example.com/img"):
            res = client.get(f"{BASE}/libraries/{public_library.uuid}")
        data = res.get_json()
        assert data["library"]["public_upload_enabled"] is False
