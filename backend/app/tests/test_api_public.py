"""
Tests for the public API endpoints: /api/v1/public/libraries/*

Coverage targets:
  GET   /api/v1/public/libraries/<uuid>                          view library
  PATCH /api/v1/public/libraries/<uuid>/images/<uuid>/state      update customer state
  POST  /api/v1/public/libraries/<uuid>/finish                   finish selection
  GET   /api/v1/public/libraries/<uuid>/images/<uuid>/download   download image
  POST  /api/v1/public/libraries/<uuid>/videos/init              customer video upload
  POST  /api/v1/public/libraries/<uuid>/videos/<uuid>/finalize   customer video finalize
  GET   /api/v1/public/libraries/<uuid>/videos/<uuid>            video status
  PATCH /api/v1/public/libraries/<uuid>/videos/<uuid>/state      update customer state
  GET   /api/v1/public/libraries/<uuid>/videos/<uuid>/download   download video
  GET   /api/v1/public/libraries/<uuid>                          videos in the media list
  GET   /api/v1/public/libraries/<uuid>/download                 ZIP including videos

Private library enforcement: all four routes must return 404 when
library.is_private is True.
"""

from datetime import datetime as _datetime

import pytest
from unittest.mock import patch
from sqlalchemy import select

from models import (
    db,
    User,
    Role,
    Library,
    Image,
    Video,
    VideoProcessingStatus,
    AuditLog,
    AuditLogType,
    CustomerState,
    SubscriptionType,
)

BASE = "/api/v1/public"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def photographer_role():
    # The photographer role is seeded by a migration; reuse it.
    role = db.session.execute(
        select(Role).where(Role.name == "photographer")
    ).scalar_one_or_none()
    if role is None:
        role = Role(name="photographer", description="Photographer")
        db.session.add(role)
        db.session.commit()
    return role


@pytest.fixture
def photographer(photographer_role):
    user = User(
        email="photo@test.com",
        active=True,
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

    def test_public_upload_strips_jpeg_metadata(self, client, upload_library):
        from test_api_images import make_jpeg_with_private_metadata, PRIVATE_JPEG_STRINGS

        jpeg = make_jpeg_with_private_metadata(orientation=6)
        with _patch("services.images.storage") as mock_storage:
            res = self._post_jpeg(client, upload_library.uuid, jpeg)
            assert res.status_code == 201
            stored = mock_storage.upload_fileobj.call_args_list[0][0][0].read()
        for needle in PRIVATE_JPEG_STRINGS:
            assert needle not in stored
        import piexif
        assert piexif.load(stored)["0th"] == {piexif.ImageIFD.Orientation: 6}

    def test_public_upload_corrupt_jpeg_rejected(self, client, upload_library):
        jpeg = _make_jpeg_bytes()[:-2]  # no EOI
        with _patch("services.images.storage") as mock_storage:
            res = self._post_jpeg(client, upload_library.uuid, jpeg)
        assert res.status_code == 415
        mock_storage.upload_fileobj.assert_not_called()

    def test_upload_invalidates_watermark_previews(self, client, upload_library):
        with _patch("services.images.storage"), _patch(
            "services.images.invalidate_watermark_previews"
        ) as mock_invalidate:
            res = self._post_jpeg(client, upload_library.uuid)
        assert res.status_code == 201
        mock_invalidate.assert_called_once_with(upload_library.id)
    
    def test_upload_enabled_accepts_webp(self, client, upload_library):
        from PIL import Image as _PilImage

        buf = _io.BytesIO()
        _PilImage.new("RGB", (2, 2), color="green").save(buf, format="WEBP")
        with _patch("services.images.storage"):
            res = client.post(
                f"{BASE}/libraries/{upload_library.uuid}/images",
                data={"file": (_io.BytesIO(buf.getvalue()), "photo.webp", "image/webp")},
                content_type="multipart/form-data",
            )
        assert res.status_code == 201
        from models import Image as _Image

        image = _Image.query.filter_by(uuid=res.get_json()["uuid"]).one()
        assert image.content_type == "image/webp"
        assert image.s3_key.endswith(".webp")

    def test_public_upload_strips_png_metadata(self, client, upload_library):
        from test_api_images import make_png_with_private_metadata, png_chunk_types

        png = make_png_with_private_metadata()
        with _patch("services.images.storage") as mock_storage:
            res = client.post(
                f"{BASE}/libraries/{upload_library.uuid}/images",
                data={"file": (_io.BytesIO(png), "photo.png", "image/png")},
                content_type="multipart/form-data",
            )
        assert res.status_code == 201
        stored = mock_storage.upload_fileobj.call_args_list[0][0][0].read()
        assert not {b"tEXt", b"zTXt", b"iTXt", b"eXIf"} & set(png_chunk_types(stored))
        assert b"SN-12345678" not in stored and b"secret-owner" not in stored
        with _PilImage.open(_io.BytesIO(stored)) as img:
            img.load()
            assert img.size == (2, 2)

    def test_public_upload_corrupt_png_rejected(self, client, upload_library):
        from test_api_images import make_png_with_private_metadata

        png = make_png_with_private_metadata()[:-6]
        with _patch("services.images.storage") as mock_storage:
            res = client.post(
                f"{BASE}/libraries/{upload_library.uuid}/images",
                data={"file": (_io.BytesIO(png), "photo.png", "image/png")},
                content_type="multipart/form-data",
            )
        assert res.status_code == 415
        mock_storage.upload_fileobj.assert_not_called()

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
        with _patch_quota(media=0), _patch("services.images.storage"):
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


# ---------------------------------------------------------------------------
# GET /api/v1/public/libraries/<uuid>/download — bulk zip download
# ---------------------------------------------------------------------------


import zipfile as _zipfile


class TestDownloadLibraryZip:
    def test_private_library_returns_404(self, client, private_library):
        res = client.get(f"{BASE}/libraries/{private_library.uuid}/download")
        assert res.status_code == 404

    def test_nonexistent_library_returns_404(self, client):
        res = client.get(f"{BASE}/libraries/00000000-0000-0000-0000-000000000000/download")
        assert res.status_code == 404

    def test_download_disabled_returns_403(self, client, public_library, image_in_library):
        res = client.get(f"{BASE}/libraries/{public_library.uuid}/download")
        assert res.status_code == 403

    def test_empty_library_returns_404(self, client, public_library):
        public_library.download_enabled = True
        db.session.commit()
        res = client.get(f"{BASE}/libraries/{public_library.uuid}/download")
        assert res.status_code == 404

    def test_streams_zip_with_all_images(self, client, public_library):
        public_library.download_enabled = True
        make_images_in_library(public_library, 3)
        stored = _datetime(2022, 3, 4, 5, 6, 8)
        for img in db.session.execute(select(Image)).scalars():
            img.created_at = stored
        db.session.commit()

        def fake_chunks(key):
            yield f"DATA-{key}".encode()

        with _patch("services.storage.iter_object_chunks", side_effect=fake_chunks):
            res = client.get(f"{BASE}/libraries/{public_library.uuid}/download")
            body = b"".join(res.response)

        assert res.status_code == 200
        assert res.mimetype == "application/zip"
        assert "attachment" in res.headers["Content-Disposition"]

        zf = _zipfile.ZipFile(_io.BytesIO(body))
        names = sorted(zf.namelist())
        assert names == ["img-0.jpg", "img-1.jpg", "img-2.jpg"]
        contents = zf.read("img-0.jpg")
        assert contents.startswith(b"DATA-photos/")
        for info in zf.infolist():
            assert info.date_time == (2022, 3, 4, 5, 6, 8)

    def test_duplicate_filenames_are_disambiguated(self, client, public_library):
        public_library.download_enabled = True
        for i in range(3):
            db.session.add(
                Image(
                    library_id=public_library.id,
                    s3_key=f"dup-{i}.jpg",
                    original_filename="same.jpg",
                    content_type="image/jpeg",
                    size=10,
                    width=1,
                    height=1,
                )
            )
        db.session.commit()

        with _patch("services.storage.iter_object_chunks", side_effect=lambda k: [b"x"]):
            res = client.get(f"{BASE}/libraries/{public_library.uuid}/download")
            body = b"".join(res.response)

        zf = _zipfile.ZipFile(_io.BytesIO(body))
        assert sorted(zf.namelist()) == ["same (1).jpg", "same (2).jpg", "same.jpg"]

    def test_uses_originals_variant_when_configured(self, client, public_library, image_in_library):
        public_library.download_enabled = True
        public_library.use_original_as_preview = True
        db.session.commit()

        seen_keys = []

        def capture(key):
            seen_keys.append(key)
            yield b"x"

        with _patch("services.storage.iter_object_chunks", side_effect=capture):
            client.get(f"{BASE}/libraries/{public_library.uuid}/download").response

        assert any("/originals/" in k for k in seen_keys)

    def test_uses_previews_variant_by_default(self, client, public_library, image_in_library):
        public_library.download_enabled = True
        db.session.commit()

        seen_keys = []

        def capture(key):
            seen_keys.append(key)
            yield b"x"

        with _patch("services.storage.iter_object_chunks", side_effect=capture):
            client.get(f"{BASE}/libraries/{public_library.uuid}/download").response

        assert any("/previews/" in k for k in seen_keys)

    def test_writes_audit_log_per_image(self, client, public_library):
        public_library.download_enabled = True
        make_images_in_library(public_library, 2)
        db.session.commit()

        from models import AuditLog, AuditLogType
        from sqlalchemy import select as _select

        with _patch("services.storage.iter_object_chunks", side_effect=lambda k: [b"x"]):
            client.get(f"{BASE}/libraries/{public_library.uuid}/download").response

        logs = db.session.execute(
            _select(AuditLog).where(AuditLog.audit_type == AuditLogType.picture_downloaded)
        ).scalars().all()
        assert len(logs) == 2


# ---------------------------------------------------------------------------
# Public upload / video init — quota boundaries
# ---------------------------------------------------------------------------

from unittest.mock import PropertyMock as _PropertyMock


def _quota_limits(storage=None, media=5000):
    return {
        "max_libraries": 10,
        "max_images_per_library": media,
        "max_storage_bytes": storage if storage is not None else 10**9,
    }


def _patch_quota(**kwargs):
    return _patch.object(
        User,
        "effective_limits",
        new_callable=_PropertyMock,
        return_value=_quota_limits(**kwargs),
    )


@pytest.fixture
def quota_library(photographer):
    lib = Library(
        user_id=photographer.id,
        name="Quota Gallery",
        is_private=False,
        public_upload_enabled=True,
    )
    db.session.add(lib)
    db.session.commit()
    return lib


def _add_media(library, count, size=1000):
    for i in range(count):
        db.session.add(
            Image(
                library_id=library.id,
                s3_key=f"q-{i}.jpg",
                original_filename=f"q-{i}.jpg",
                content_type="image/jpeg",
                size=size,
            )
        )
    db.session.commit()


class TestPublicUploadImageQuotas:
    def _post(self, client, library):
        return client.post(
            f"{BASE}/libraries/{library.uuid}/images",
            data={"file": (_io.BytesIO(_make_jpeg_bytes()), "p.jpg", "image/jpeg")},
            content_type="multipart/form-data",
        )

    def test_media_count_below_limit_allowed(self, client, quota_library):
        _add_media(quota_library, 2)
        with _patch_quota(media=3), _patch("services.images.storage"):
            assert self._post(client, quota_library).status_code == 201

    def test_media_count_at_limit_rejected(self, client, quota_library):
        _add_media(quota_library, 3)
        with _patch_quota(media=3), _patch("services.images.storage"):
            assert self._post(client, quota_library).status_code == 422

    def test_storage_exactly_at_limit_allowed(self, client, quota_library):
        size = len(_make_jpeg_bytes())
        _add_media(quota_library, 1)
        with _patch_quota(storage=1000 + size), _patch("services.images.storage"):
            assert self._post(client, quota_library).status_code == 201

    def test_storage_one_byte_over_rejected(self, client, quota_library):
        size = len(_make_jpeg_bytes())
        _add_media(quota_library, 1)
        with _patch_quota(storage=1000 + size - 1), _patch("services.images.storage"):
            assert self._post(client, quota_library).status_code == 422

    def test_storage_overshoot_rejected(self, client, quota_library):
        _add_media(quota_library, 1)
        with _patch_quota(storage=1010), _patch("services.images.storage"):
            res = self._post(client, quota_library)
        assert res.status_code == 422
        assert res.get_json()["error"].endswith("for this library.")


class TestPublicVideoInitQuotas:
    SIZE = 5000

    def _post(self, client, library):
        return client.post(
            f"{BASE}/libraries/{library.uuid}/videos/init",
            json={"filename": "v.mp4", "content_type": "video/mp4", "size": self.SIZE},
        )

    @pytest.fixture(autouse=True)
    def video_enabled(self):
        with _patch("blueprints.api.public.VIDEO_UPLOADS_ENABLED", True), _patch(
            "services.videos.storage"
        ) as st:
            st.create_presigned_put_url.return_value = "http://example.com/put"
            yield

    def test_media_count_below_limit_allowed(self, client, quota_library):
        _add_media(quota_library, 2)
        with _patch_quota(media=3):
            assert self._post(client, quota_library).status_code == 201

    def test_media_count_at_limit_rejected(self, client, quota_library):
        _add_media(quota_library, 3)
        with _patch_quota(media=3):
            assert self._post(client, quota_library).status_code == 422

    def test_storage_exactly_at_limit_allowed(self, client, quota_library):
        _add_media(quota_library, 1)
        with _patch_quota(storage=1000 + self.SIZE):
            assert self._post(client, quota_library).status_code == 201

    def test_storage_one_byte_over_rejected(self, client, quota_library):
        _add_media(quota_library, 1)
        with _patch_quota(storage=1000 + self.SIZE - 1):
            assert self._post(client, quota_library).status_code == 422

    def test_storage_overshoot_rejected(self, client, quota_library):
        _add_media(quota_library, 1)
        with _patch_quota(storage=1000 + self.SIZE // 2):
            res = self._post(client, quota_library)
        assert res.status_code == 422
        assert res.get_json()["error"].endswith("for this library.")


# ---------------------------------------------------------------------------
# Public video routes
# ---------------------------------------------------------------------------

PUBLIC_VIDEO_UUID = "22222222-2222-2222-2222-222222222222"
MISSING_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def video_enabled():
    with _patch("blueprints.api.public.VIDEO_UPLOADS_ENABLED", True):
        yield


@pytest.fixture
def upload_library(photographer):
    lib = Library(
        user_id=photographer.id,
        name="Upload Gallery",
        is_private=False,
        public_upload_enabled=True,
    )
    db.session.add(lib)
    db.session.commit()
    return lib


def _add_video(
    library,
    status=VideoProcessingStatus.uploading,
    is_external=True,
    uuid=PUBLIC_VIDEO_UUID,
    filename="clip.mp4",
):
    video = Video(
        uuid=uuid,
        library_id=library.id,
        s3_key=f"{uuid}.mp4",
        original_filename=filename,
        content_type="video/mp4",
        size=1000,
        width=1280,
        height=720,
        duration_ms=4000,
        processing_status=status,
        is_external=is_external,
    )
    db.session.add(video)
    db.session.commit()
    return video


def _audit_logs(audit_type):
    return (
        db.session.execute(select(AuditLog).where(AuditLog.audit_type == audit_type))
        .scalars()
        .all()
    )


class TestPublicVideoFeatureGate:
    """Without VIDEO_UPLOADS_ENABLED the upload and status routes answer 501."""

    def test_init_returns_501(self, client, upload_library):
        res = client.post(
            f"{BASE}/libraries/{upload_library.uuid}/videos/init",
            json={"filename": "v.mp4", "content_type": "video/mp4", "size": 10},
        )
        assert res.status_code == 501

    def test_finalize_returns_501(self, client, upload_library):
        res = client.post(
            f"{BASE}/libraries/{upload_library.uuid}/videos/{PUBLIC_VIDEO_UUID}/finalize"
        )
        assert res.status_code == 501

    def test_status_returns_501(self, client, upload_library):
        res = client.get(
            f"{BASE}/libraries/{upload_library.uuid}/videos/{PUBLIC_VIDEO_UUID}"
        )
        assert res.status_code == 501


class TestPublicVideoUngatedRoutes:
    """The state and download routes carry no VIDEO_UPLOADS_ENABLED check (only
    init, finalize and status do), so they keep working with the gate closed."""

    def test_state_route_is_not_gated(self, client, public_library):
        _add_video(public_library)
        res = client.patch(
            f"{BASE}/libraries/{public_library.uuid}/videos/{PUBLIC_VIDEO_UUID}/state",
            json={"customer_state": "liked"},
        )
        assert res.status_code == 200

    def test_download_route_is_not_gated(self, client, public_library):
        public_library.download_enabled = True
        _add_video(public_library, status=VideoProcessingStatus.ready)
        db.session.commit()
        with _patch("blueprints.api.public.storage") as st:
            st.get_presigned_download_url.return_value = "http://example.com/dl"
            res = client.get(
                f"{BASE}/libraries/{public_library.uuid}/videos/{PUBLIC_VIDEO_UUID}/download"
            )
        assert res.status_code == 200

    @pytest.mark.parametrize(
        "status",
        [
            VideoProcessingStatus.uploading,
            VideoProcessingStatus.processing,
            VideoProcessingStatus.failed,
        ],
    )
    def test_download_of_non_ready_video_returns_404(
        self, client, public_library, status
    ):
        public_library.download_enabled = True
        _add_video(public_library, status=status)
        db.session.commit()
        with _patch("blueprints.api.public.storage") as st:
            res = client.get(
                f"{BASE}/libraries/{public_library.uuid}/videos/{PUBLIC_VIDEO_UUID}/download"
            )
        assert res.status_code == 404
        st.get_presigned_download_url.assert_not_called()


@pytest.mark.usefixtures("video_enabled")
class TestPublicVideoInit:
    PAYLOAD = {"filename": "v.mp4", "content_type": "video/mp4", "size": 5000}

    def _post(self, client, library_uuid, **overrides):
        body = {**self.PAYLOAD, **overrides}
        body = {k: v for k, v in body.items() if v is not None}
        return client.post(f"{BASE}/libraries/{library_uuid}/videos/init", json=body)

    def test_nonexistent_library_returns_404(self, client):
        assert self._post(client, MISSING_UUID).status_code == 404

    def test_soft_deleted_library_returns_404(self, client, upload_library):
        upload_library.deleted_at = _datetime(2024, 1, 1)
        db.session.commit()
        assert self._post(client, upload_library.uuid).status_code == 404

    def test_private_library_returns_404(self, client, upload_library):
        upload_library.is_private = True
        db.session.commit()
        assert self._post(client, upload_library.uuid).status_code == 404

    def test_public_upload_disabled_returns_403(self, client, public_library):
        assert self._post(client, public_library.uuid).status_code == 403

    @pytest.mark.parametrize("size", [None, 0, -1, "5"])
    def test_invalid_size_returns_400(self, client, upload_library, size):
        assert self._post(client, upload_library.uuid, size=size).status_code == 400

    def test_invalid_content_type_returns_422(self, client, upload_library):
        res = self._post(client, upload_library.uuid, content_type="image/jpeg")
        assert res.status_code == 422

    def test_missing_filename_returns_422(self, client, upload_library):
        assert self._post(client, upload_library.uuid, filename=" ").status_code == 422

    def test_storage_failure_returns_502(self, client, upload_library):
        with _patch("services.videos.storage") as st:
            st.create_presigned_put_url.side_effect = RuntimeError("s3 down")
            res = self._post(client, upload_library.uuid)
        assert res.status_code == 502
        assert db.session.execute(select(Video)).scalars().all() == []

    def test_success_creates_external_video_without_creator(
        self, client, upload_library
    ):
        with _patch("services.videos.storage") as st:
            st.create_presigned_put_url.return_value = "http://example.com/put"
            res = self._post(client, upload_library.uuid)

        assert res.status_code == 201
        body = res.get_json()
        assert body["upload_url"] == "http://example.com/put"
        video = db.session.execute(select(Video)).scalar_one()
        assert video.uuid == body["uuid"]
        assert video.is_external is True
        assert video.processing_status == VideoProcessingStatus.uploading
        (log,) = _audit_logs(AuditLogType.video_uploaded)
        assert log.creator_id is None
        assert log.related_object_id == video.uuid


@pytest.mark.usefixtures("video_enabled")
class TestPublicVideoFinalize:
    @pytest.fixture(autouse=True)
    def storage(self):
        with _patch("services.videos.storage") as st:
            st.object_exists.return_value = True
            self.storage = st
            yield

    def _post(self, client, library_uuid, video_uuid=PUBLIC_VIDEO_UUID):
        return client.post(
            f"{BASE}/libraries/{library_uuid}/videos/{video_uuid}/finalize"
        )

    def test_nonexistent_library_returns_404(self, client):
        assert self._post(client, MISSING_UUID).status_code == 404

    def test_private_library_returns_404(self, client, upload_library):
        _add_video(upload_library)
        upload_library.is_private = True
        db.session.commit()
        assert self._post(client, upload_library.uuid).status_code == 404

    def test_public_upload_disabled_returns_403(self, client, upload_library):
        _add_video(upload_library)
        upload_library.public_upload_enabled = False
        db.session.commit()
        assert self._post(client, upload_library.uuid).status_code == 403

    def test_nonexistent_video_returns_404(self, client, upload_library):
        assert self._post(client, upload_library.uuid).status_code == 404

    def test_photographer_video_cannot_be_finalized_publicly(
        self, client, upload_library
    ):
        _add_video(upload_library, is_external=False)

        res = self._post(client, upload_library.uuid)

        assert res.status_code == 404
        video = db.session.execute(select(Video)).scalar_one()
        assert video.processing_status == VideoProcessingStatus.uploading

    def test_video_of_other_library_returns_404(
        self, client, upload_library, public_library
    ):
        _add_video(public_library)
        assert self._post(client, upload_library.uuid).status_code == 404

    def test_soft_deleted_video_returns_404(self, client, upload_library):
        video = _add_video(upload_library)
        video.deleted_at = _datetime(2024, 1, 1)
        db.session.commit()
        assert self._post(client, upload_library.uuid).status_code == 404

    @pytest.mark.parametrize(
        "status", [VideoProcessingStatus.processing, VideoProcessingStatus.ready]
    )
    def test_not_uploading_returns_409(self, client, upload_library, status):
        _add_video(upload_library, status=status)
        assert self._post(client, upload_library.uuid).status_code == 409

    def test_missing_object_returns_422(self, client, upload_library):
        _add_video(upload_library)
        self.storage.object_exists.return_value = False
        assert self._post(client, upload_library.uuid).status_code == 422

    def test_unexpected_error_returns_502(self, client, upload_library):
        _add_video(upload_library)
        self.storage.object_exists.side_effect = RuntimeError("s3 down")
        assert self._post(client, upload_library.uuid).status_code == 502

    def test_success_enqueues_processing(self, client, upload_library):
        from sqlalchemy import text

        _add_video(upload_library)

        res = self._post(client, upload_library.uuid)

        assert res.status_code == 200
        assert res.get_json() == {
            "uuid": PUBLIC_VIDEO_UUID,
            "processing_status": "processing",
        }
        video = db.session.execute(select(Video)).scalar_one()
        assert video.processing_status == VideoProcessingStatus.processing
        jobs = db.session.execute(
            text("SELECT queue_name, args FROM procrastinate_jobs")
        ).mappings().all()
        assert len(jobs) == 1
        assert jobs[0]["queue_name"] == "video"
        assert jobs[0]["args"] == {"video_uuid": PUBLIC_VIDEO_UUID}


@pytest.mark.usefixtures("video_enabled")
class TestPublicVideoStatus:
    def _get(self, client, library_uuid, video_uuid=PUBLIC_VIDEO_UUID):
        return client.get(f"{BASE}/libraries/{library_uuid}/videos/{video_uuid}")

    def test_nonexistent_library_returns_404(self, client):
        assert self._get(client, MISSING_UUID).status_code == 404

    def test_soft_deleted_library_returns_404(self, client, public_library):
        _add_video(public_library)
        public_library.deleted_at = _datetime(2024, 1, 1)
        db.session.commit()
        assert self._get(client, public_library.uuid).status_code == 404

    def test_private_library_returns_404(self, client, private_library):
        _add_video(private_library)
        assert self._get(client, private_library.uuid).status_code == 404

    def test_nonexistent_video_returns_404(self, client, public_library):
        assert self._get(client, public_library.uuid).status_code == 404

    def test_soft_deleted_video_returns_404(self, client, public_library):
        video = _add_video(public_library)
        video.deleted_at = _datetime(2024, 1, 1)
        db.session.commit()
        assert self._get(client, public_library.uuid).status_code == 404

    def test_returns_status(self, client, public_library):
        _add_video(public_library, status=VideoProcessingStatus.processing)
        res = self._get(client, public_library.uuid)
        assert res.status_code == 200
        assert res.get_json() == {
            "uuid": PUBLIC_VIDEO_UUID,
            "processing_status": "processing",
            "hevc_warning": False,
        }

    def test_reports_hevc_warning(self, client, public_library):
        video = _add_video(public_library, status=VideoProcessingStatus.ready)
        video.hevc_warning = True
        db.session.commit()
        body = self._get(client, public_library.uuid).get_json()
        assert body["processing_status"] == "ready"
        assert body["hevc_warning"] is True


class TestPublicVideoCustomerState:
    def _patch(self, client, library_uuid, state="liked", video_uuid=PUBLIC_VIDEO_UUID):
        return client.patch(
            f"{BASE}/libraries/{library_uuid}/videos/{video_uuid}/state",
            json={"customer_state": state},
        )

    def test_invalid_state_returns_400(self, client, public_library):
        _add_video(public_library)
        assert self._patch(client, public_library.uuid, "bogus").status_code == 400

    def test_missing_state_returns_400(self, client, public_library):
        _add_video(public_library)
        res = client.patch(
            f"{BASE}/libraries/{public_library.uuid}/videos/{PUBLIC_VIDEO_UUID}/state",
            json={},
        )
        assert res.status_code == 400

    def test_nonexistent_library_returns_404(self, client):
        assert self._patch(client, MISSING_UUID).status_code == 404

    def test_soft_deleted_library_returns_404(self, client, public_library):
        _add_video(public_library)
        public_library.deleted_at = _datetime(2024, 1, 1)
        db.session.commit()
        assert self._patch(client, public_library.uuid).status_code == 404

    def test_private_library_returns_404(self, client, private_library):
        _add_video(private_library)
        res = self._patch(client, private_library.uuid)
        assert res.status_code == 404
        video = db.session.execute(select(Video)).scalar_one()
        assert video.customer_state == CustomerState.none

    def test_nonexistent_video_returns_404(self, client, public_library):
        assert self._patch(client, public_library.uuid).status_code == 404

    def test_video_of_other_library_returns_404(
        self, client, public_library, upload_library
    ):
        _add_video(upload_library)
        assert self._patch(client, public_library.uuid).status_code == 404

    def test_like_and_unlike(self, client, public_library):
        _add_video(public_library)

        res = self._patch(client, public_library.uuid, "liked")
        assert res.status_code == 200
        assert res.get_json() == {"uuid": PUBLIC_VIDEO_UUID, "customer_state": "liked"}
        assert (
            db.session.execute(select(Video)).scalar_one().customer_state
            == CustomerState.liked
        )

        res = self._patch(client, public_library.uuid, "none")
        assert res.get_json()["customer_state"] == "none"
        db.session.expire_all()
        assert (
            db.session.execute(select(Video)).scalar_one().customer_state
            == CustomerState.none
        )

    def test_invalidates_public_cache(self, client, public_library):
        _add_video(public_library)
        with _patch("blueprints.api.public.cache_delete_pattern") as cdp:
            self._patch(client, public_library.uuid)
        cdp.assert_called_once_with(f"public:library:{public_library.uuid}:*")


class TestPublicVideoDownload:
    def _get(self, client, library_uuid, video_uuid=PUBLIC_VIDEO_UUID):
        return client.get(
            f"{BASE}/libraries/{library_uuid}/videos/{video_uuid}/download"
        )

    @pytest.fixture
    def download_library(self, public_library):
        public_library.download_enabled = True
        db.session.commit()
        return public_library

    def test_nonexistent_library_returns_404(self, client):
        assert self._get(client, MISSING_UUID).status_code == 404

    def test_private_library_returns_404(self, client, private_library):
        private_library.download_enabled = True
        _add_video(private_library, status=VideoProcessingStatus.ready)
        assert self._get(client, private_library.uuid).status_code == 404

    def test_download_disabled_returns_403(self, client, public_library):
        _add_video(public_library, status=VideoProcessingStatus.ready)
        assert self._get(client, public_library.uuid).status_code == 403
        assert _audit_logs(AuditLogType.video_downloaded) == []

    def test_nonexistent_video_returns_404(self, client, download_library):
        assert self._get(client, download_library.uuid).status_code == 404

    def test_soft_deleted_video_returns_404(self, client, download_library):
        video = _add_video(download_library, status=VideoProcessingStatus.ready)
        video.deleted_at = _datetime(2024, 1, 1)
        db.session.commit()
        assert self._get(client, download_library.uuid).status_code == 404

    @pytest.mark.parametrize(
        "status",
        [
            VideoProcessingStatus.uploading,
            VideoProcessingStatus.processing,
            VideoProcessingStatus.failed,
        ],
    )
    def test_non_ready_video_returns_404(self, client, download_library, status):
        _add_video(download_library, status=status)
        with _patch("blueprints.api.public.storage") as st:
            res = self._get(client, download_library.uuid)
        assert res.status_code == 404
        assert res.get_json() == {"error": "Video not found"}
        st.get_presigned_download_url.assert_not_called()
        assert _audit_logs(AuditLogType.video_downloaded) == []

    def test_success_returns_url_and_logs(self, client, download_library):
        video = _add_video(download_library, status=VideoProcessingStatus.ready)
        with _patch("blueprints.api.public.storage") as st:
            st.get_presigned_download_url.return_value = "http://example.com/dl"
            res = self._get(client, download_library.uuid)

        assert res.status_code == 200
        assert res.get_json() == {"download_url": "http://example.com/dl"}
        st.get_presigned_download_url.assert_called_once_with(
            video.storage_path("originals"), "clip.mp4"
        )
        (log,) = _audit_logs(AuditLogType.video_downloaded)
        assert log.related_object_id == video.uuid
        assert log.creator_id is None


class TestPublicLibraryVideos:
    @pytest.fixture(autouse=True)
    def presign(self):
        with _patch("blueprints.api.public.storage") as st:
            st.get_presigned_url.side_effect = lambda key: f"http://s3/{key}"
            st.get_presigned_download_url.side_effect = (
                lambda key, name: f"http://s3/dl/{key}"
            )
            self.storage = st
            yield

    def _items(self, client, library):
        res = client.get(f"{BASE}/libraries/{library.uuid}")
        assert res.status_code == 200
        return res.get_json()

    def test_ready_video_is_listed_with_urls(self, client, public_library):
        video = _add_video(public_library, status=VideoProcessingStatus.ready)

        body = self._items(client, public_library)

        assert body["total"] == 1
        (item,) = body["images"]
        assert item["media_type"] == "video"
        assert item["uuid"] == video.uuid
        assert item["processing_status"] == "ready"
        assert item["duration_ms"] == 4000
        # Intended for videos: there is no preview transcode, so the original is
        # streamed as the preview (see "Video Uploads" in CLAUDE.md).
        assert item["preview_url"] == f"http://s3/{video.storage_path('originals')}"
        assert item["thumb_url"] == f"http://s3/{video.storage_path('thumbs')}"
        assert item["download_url"] is None

    def test_unfinished_video_has_no_urls(self, client, public_library):
        _add_video(public_library, status=VideoProcessingStatus.processing)
        (item,) = self._items(client, public_library)["images"]
        assert item["processing_status"] == "processing"
        assert item["preview_url"] is None
        assert item["thumb_url"] is None
        assert item["download_url"] is None

    def test_download_url_when_downloads_enabled(self, client, public_library):
        public_library.download_enabled = True
        video = _add_video(public_library, status=VideoProcessingStatus.ready)
        db.session.commit()
        (item,) = self._items(client, public_library)["images"]
        assert item["download_url"] == f"http://s3/dl/{video.storage_path('originals')}"

    def test_deleted_video_is_not_listed(self, client, public_library):
        video = _add_video(public_library, status=VideoProcessingStatus.ready)
        video.deleted_at = _datetime(2024, 1, 1)
        db.session.commit()
        assert self._items(client, public_library)["total"] == 0

    def test_images_and_videos_are_merged(self, client, public_library):
        make_images_in_library(public_library, 2)
        _add_video(public_library, status=VideoProcessingStatus.ready)

        body = self._items(client, public_library)

        assert body["total"] == 3
        assert sorted(i["media_type"] for i in body["images"]) == [
            "photo",
            "photo",
            "video",
        ]

    @pytest.mark.parametrize("enabled", [True, False])
    def test_reports_video_uploads_flag(self, client, public_library, enabled):
        with _patch("blueprints.api.public.VIDEO_UPLOADS_ENABLED", enabled):
            body = self._items(client, public_library)
        assert body["library"]["video_uploads_enabled"] is enabled


class TestDownloadLibraryZipWithVideos:
    @pytest.fixture
    def zip_library(self, public_library):
        public_library.download_enabled = True
        db.session.commit()
        return public_library

    def _zip(self, client, library):
        def fake_chunks(key):
            yield f"DATA-{key}".encode()

        with _patch("services.storage.iter_object_chunks", side_effect=fake_chunks):
            res = client.get(f"{BASE}/libraries/{library.uuid}/download")
            body = b"".join(res.response)
        return res, body

    def test_library_with_only_a_video_is_downloadable(self, client, zip_library):
        video = _add_video(zip_library, status=VideoProcessingStatus.ready)

        res, body = self._zip(client, zip_library)

        assert res.status_code == 200
        zf = _zipfile.ZipFile(_io.BytesIO(body))
        assert zf.namelist() == ["clip.mp4"]
        assert zf.read("clip.mp4") == f"DATA-{video.storage_path('originals')}".encode()

    def test_images_and_videos_share_one_archive(self, client, zip_library):
        make_images_in_library(zip_library, 1)
        _add_video(zip_library, status=VideoProcessingStatus.ready)

        _, body = self._zip(client, zip_library)

        zf = _zipfile.ZipFile(_io.BytesIO(body))
        assert sorted(zf.namelist()) == ["clip.mp4", "img-0.jpg"]

    @pytest.mark.parametrize(
        "status",
        [
            VideoProcessingStatus.uploading,
            VideoProcessingStatus.processing,
            VideoProcessingStatus.failed,
        ],
    )
    def test_unfinished_videos_are_skipped(self, client, zip_library, status):
        make_images_in_library(zip_library, 1)
        _add_video(zip_library, status=status)

        _, body = self._zip(client, zip_library)

        assert _zipfile.ZipFile(_io.BytesIO(body)).namelist() == ["img-0.jpg"]

    def test_only_unfinished_videos_counts_as_empty(self, client, zip_library):
        _add_video(zip_library, status=VideoProcessingStatus.processing)
        res = client.get(f"{BASE}/libraries/{zip_library.uuid}/download")
        assert res.status_code == 404

    def test_deleted_video_is_skipped(self, client, zip_library):
        make_images_in_library(zip_library, 1)
        video = _add_video(zip_library, status=VideoProcessingStatus.ready)
        video.deleted_at = _datetime(2024, 1, 1)
        db.session.commit()

        _, body = self._zip(client, zip_library)

        assert _zipfile.ZipFile(_io.BytesIO(body)).namelist() == ["img-0.jpg"]

    def test_writes_video_audit_log(self, client, zip_library):
        video = _add_video(zip_library, status=VideoProcessingStatus.ready)

        self._zip(client, zip_library)

        (log,) = _audit_logs(AuditLogType.video_downloaded)
        assert log.related_object_id == video.uuid
