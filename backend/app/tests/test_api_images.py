"""
Tests for the JSON API images endpoints: /api/v1/libraries/<id>/images/*

Coverage targets:
  POST   /api/v1/libraries/<id>/images          upload image
  - rejects disallowed content types
  - rejects spoofed content type (wrong magic bytes)
  - rejects corrupt image data
  - accepts valid JPEG
  - accepts valid PNG
  - strips private EXIF (GPS, serial numbers, MakerNote) from JPEG originals
"""

import io
import os
import tempfile
from unittest.mock import patch

import piexif
import pytest
from PIL import Image as PilImage, ImageOps

from datetime import datetime, timezone

from sqlalchemy import select

from models import db, User, Role, Library, Image, Video, VideoProcessingStatus
from services.token import create_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_token(user: User) -> str:
    return create_token(user.id, user.email, [r.name for r in user.roles])


def make_jpeg_bytes() -> bytes:
    """Create a minimal valid JPEG in memory."""
    buf = io.BytesIO()
    img = PilImage.new("RGB", (2, 2), color="red")
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_jpeg_with_private_exif() -> bytes:
    """Create a JPEG that contains GPS coordinates and a body serial number."""
    base = make_jpeg_bytes()
    exif_dict = {
        "0th": {},
        "Exif": {
            piexif.ExifIFD.BodySerialNumber: b"SN-12345678",
            piexif.ExifIFD.LensSerialNumber: b"LENS-99",
            piexif.ExifIFD.CameraOwnerName: b"John Doe",
            piexif.ExifIFD.MakerNote: b"\x00\x01some proprietary data",
        },
        "GPS": {
            piexif.GPSIFD.GPSLatitude: ((48, 1), (12, 1), (0, 1)),
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLongitude: ((16, 1), (22, 1), (0, 1)),
            piexif.GPSIFD.GPSLongitudeRef: b"E",
        },
        "1st": {},
        "thumbnail": None,
    }
    fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
    try:
        os.write(fd, base)
        os.close(fd)
        piexif.insert(piexif.dump(exif_dict), tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


def make_png_bytes() -> bytes:
    """Create a minimal valid PNG in memory."""
    buf = io.BytesIO()
    img = PilImage.new("RGB", (2, 2), color="blue")
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_webp_bytes() -> bytes:
    """Create a minimal valid WebP in memory."""
    buf = io.BytesIO()
    img = PilImage.new("RGB", (2, 2), color="green")
    img.save(buf, format="WEBP")
    return buf.getvalue()


def make_webp_with_private_metadata() -> bytes:
    """Create a WebP that contains GPS + serial number EXIF and an XMP packet."""
    exif_bytes = piexif.dump(
        {
            "0th": {},
            "Exif": {piexif.ExifIFD.BodySerialNumber: b"SN-12345678"},
            "GPS": {
                piexif.GPSIFD.GPSLatitude: ((48, 1), (12, 1), (0, 1)),
                piexif.GPSIFD.GPSLatitudeRef: b"N",
            },
            "1st": {},
            "thumbnail": None,
        }
    )
    buf = io.BytesIO()
    PilImage.new("RGB", (2, 2), color="green").save(
        buf, format="WEBP", exif=exif_bytes, xmp=b"<x:xmpmeta>secret-owner</x:xmpmeta>"
    )
    return buf.getvalue()


def upload(client, library_id, token, data, filename, content_type):
    """POST a file upload to the images endpoint."""
    return client.post(
        f"/api/v1/libraries/{library_id}/images",
        data={"file": (io.BytesIO(data), filename, content_type)},
        headers=auth_header(token),
        content_type="multipart/form-data",
    )


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
    user = User(email="photo@test.com", active=True)
    user.set_password("PhotoPass123!")
    user.roles.append(photographer_role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def library(photographer):
    lib = Library(user_id=photographer.id, name="Test Library")
    db.session.add(lib)
    db.session.commit()
    return lib


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------


class TestUploadContentTypeValidation:
    """The endpoint must reject files whose content type is not allowed."""

    def test_rejects_text_plain(self, client, photographer, library):
        token = make_token(photographer)
        res = upload(client, library.id, token, b"hello", "file.txt", "text/plain")
        assert res.status_code == 415
        assert "Only JPEG, PNG, and WebP" in res.get_json()["error"]

    def test_rejects_application_pdf(self, client, photographer, library):
        token = make_token(photographer)
        res = upload(client, library.id, token, b"%PDF-1.4", "doc.pdf", "application/pdf")
        assert res.status_code == 415

    def test_rejects_image_gif(self, client, photographer, library):
        token = make_token(photographer)
        res = upload(client, library.id, token, b"GIF89a", "anim.gif", "image/gif")
        assert res.status_code == 415

    def test_rejects_image_svg(self, client, photographer, library):
        token = make_token(photographer)
        svg = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
        res = upload(client, library.id, token, svg, "icon.svg", "image/svg+xml")
        assert res.status_code == 415


class TestUploadMagicByteValidation:
    """The endpoint must reject files where the magic bytes don't match the
    declared content type — even if Content-Type is in the allowlist."""

    def test_rejects_text_disguised_as_jpeg(self, client, photographer, library):
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            b"this is not a jpeg", "fake.jpg", "image/jpeg",
        )
        assert res.status_code == 415
        assert "does not match" in res.get_json()["error"]

    def test_rejects_text_disguised_as_png(self, client, photographer, library):
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            b"this is not a png", "fake.png", "image/png",
        )
        assert res.status_code == 415
        assert "does not match" in res.get_json()["error"]

    def test_rejects_png_bytes_with_jpeg_content_type(self, client, photographer, library):
        """Real PNG data, but Content-Type claims JPEG — magic bytes mismatch."""
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            make_png_bytes(), "photo.jpg", "image/jpeg",
        )
        assert res.status_code == 415
        assert "does not match" in res.get_json()["error"]

    def test_rejects_jpeg_bytes_with_png_content_type(self, client, photographer, library):
        """Real JPEG data, but Content-Type claims PNG — magic bytes mismatch."""
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            make_jpeg_bytes(), "photo.png", "image/png",
        )
        assert res.status_code == 415
        assert "does not match" in res.get_json()["error"]

    def test_rejects_text_disguised_as_webp(self, client, photographer, library):
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            b"this is not a webp", "fake.webp", "image/webp",
        )
        assert res.status_code == 415
        assert "does not match" in res.get_json()["error"]

    def test_rejects_webp_bytes_with_jpeg_content_type(self, client, photographer, library):
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            make_webp_bytes(), "photo.jpg", "image/jpeg",
        )
        assert res.status_code == 415
        assert "does not match" in res.get_json()["error"]

    def test_rejects_jpeg_bytes_with_webp_content_type(self, client, photographer, library):
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            make_jpeg_bytes(), "photo.webp", "image/webp",
        )
        assert res.status_code == 415
        assert "does not match" in res.get_json()["error"]

    def test_rejects_riff_non_webp_disguised_as_webp(self, client, photographer, library):
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            b"RIFF\x00\x00\x00\x00WAVE", "audio.webp", "image/webp",
        )
        assert res.status_code == 415
        assert "does not match" in res.get_json()["error"]

    def test_rejects_webp_magic_bytes_but_corrupt_body(self, client, photographer, library):
        token = make_token(photographer)
        corrupt = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100
        res = upload(
            client, library.id, token,
            corrupt, "corrupt.webp", "image/webp",
        )
        assert res.status_code == 415
        assert "not a valid image" in res.get_json()["error"]

    def test_rejects_correct_magic_bytes_but_corrupt_body(
        self, client, photographer, library
    ):
        """File starts with JPEG magic bytes but the rest is garbage — Pillow rejects it."""
        token = make_token(photographer)
        corrupt = b"\xff\xd8\xff" + b"\x00" * 100
        res = upload(
            client, library.id, token,
            corrupt, "corrupt.jpg", "image/jpeg",
        )
        assert res.status_code == 415
        assert "not a valid image" in res.get_json()["error"]


class TestUploadValidImages:
    """Valid images with correct content types must be accepted (storage mocked)."""

    @patch("services.images.storage")
    def test_accepts_valid_jpeg(self, mock_storage, client, photographer, library):
        mock_storage.get_presigned_url.side_effect = lambda key: f"http://example.com/{key}"
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            make_jpeg_bytes(), "photo.jpg", "image/jpeg",
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["content_type"] == "image/jpeg"
        assert data["width"] == 2
        assert data["height"] == 2
        assert data["original_url"] is not None
        assert data["preview_url"] is not None
        assert data["thumb_url"] is not None
        mock_storage.ensure_bucket.assert_called_once()
        # Three uploads: original + preview + thumbnail
        assert mock_storage.upload_fileobj.call_count == 3
        calls = mock_storage.upload_fileobj.call_args_list
        original_key = calls[0][0][1]
        preview_key = calls[1][0][1]
        thumb_key = calls[2][0][1]
        assert original_key.startswith(f"photos/{photographer.id}/{library.id}/originals/")
        assert original_key.endswith(".jpg")
        assert preview_key.startswith(f"photos/{photographer.id}/{library.id}/previews/")
        assert preview_key.endswith(".jpg")
        assert thumb_key.startswith(f"photos/{photographer.id}/{library.id}/thumbs/")
        assert thumb_key.endswith(".jpg")

    @patch("services.images.storage")
    def test_accepts_valid_png(self, mock_storage, client, photographer, library):
        mock_storage.get_presigned_url.side_effect = lambda key: f"http://example.com/{key}"
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            make_png_bytes(), "photo.png", "image/png",
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["content_type"] == "image/png"
        assert data["original_url"] is not None
        assert data["preview_url"] is not None
        assert data["thumb_url"] is not None
        mock_storage.ensure_bucket.assert_called_once()
        assert mock_storage.upload_fileobj.call_count == 3
        calls = mock_storage.upload_fileobj.call_args_list
        original_key = calls[0][0][1]
        preview_key = calls[1][0][1]
        thumb_key = calls[2][0][1]
        assert original_key.startswith(f"photos/{photographer.id}/{library.id}/originals/")
        assert original_key.endswith(".png")
        assert preview_key.startswith(f"photos/{photographer.id}/{library.id}/previews/")
        assert preview_key.endswith(".png")
        assert thumb_key.startswith(f"photos/{photographer.id}/{library.id}/thumbs/")
        assert thumb_key.endswith(".png")

    @patch("services.images.storage")
    def test_accepts_valid_webp(self, mock_storage, client, photographer, library):
        mock_storage.get_presigned_url.side_effect = lambda key: f"http://example.com/{key}"
        token = make_token(photographer)
        res = upload(
            client, library.id, token,
            make_webp_bytes(), "photo.webp", "image/webp",
        )
        assert res.status_code == 201
        data = res.get_json()
        assert data["content_type"] == "image/webp"
        assert data["width"] == 2
        assert data["height"] == 2
        assert mock_storage.upload_fileobj.call_count == 3
        calls = mock_storage.upload_fileobj.call_args_list
        assert calls[0][0][1].startswith(f"photos/{photographer.id}/{library.id}/originals/")
        assert calls[0][0][1].endswith(".webp")
        assert calls[1][0][1].endswith(".webp")
        assert calls[2][0][1].endswith(".webp")


class TestExifStripping:
    """GPS and device-identifying EXIF tags must be removed from JPEG originals."""

    @patch("services.images.storage")
    def test_gps_and_serial_stripped_from_original(
        self, mock_storage, client, photographer, library
    ):
        mock_storage.get_presigned_url.side_effect = lambda key: f"http://example.com/{key}"
        token = make_token(photographer)
        jpeg_with_exif = make_jpeg_with_private_exif()

        res = upload(
            client, library.id, token,
            jpeg_with_exif, "geotagged.jpg", "image/jpeg",
        )
        assert res.status_code == 201

        # The first upload_fileobj call is the original
        calls = mock_storage.upload_fileobj.call_args_list
        original_buf: io.BytesIO = calls[0][0][0]
        stored_bytes = original_buf.read()

        exif_dict = piexif.load(stored_bytes)
        assert exif_dict.get("GPS") == {}, "GPS IFD must be empty"
        exif_ifd = exif_dict.get("Exif", {})
        assert piexif.ExifIFD.BodySerialNumber not in exif_ifd
        assert piexif.ExifIFD.LensSerialNumber not in exif_ifd
        assert piexif.ExifIFD.CameraOwnerName not in exif_ifd
        assert piexif.ExifIFD.MakerNote not in exif_ifd

    @patch("services.images.storage")
    def test_exif_and_xmp_stripped_from_webp_original(
        self, mock_storage, client, photographer, library
    ):
        mock_storage.get_presigned_url.side_effect = lambda key: f"http://example.com/{key}"
        token = make_token(photographer)
        webp = make_webp_with_private_metadata()
        assert b"EXIF" in webp and b"XMP " in webp and b"SN-12345678" in webp

        res = upload(client, library.id, token, webp, "geotagged.webp", "image/webp")
        assert res.status_code == 201

        stored = mock_storage.upload_fileobj.call_args_list[0][0][0].read()
        assert b"EXIF" not in stored and b"XMP " not in stored
        assert b"SN-12345678" not in stored and b"secret-owner" not in stored
        assert int.from_bytes(stored[4:8], "little") == len(stored) - 8
        with PilImage.open(io.BytesIO(stored)) as img:
            img.load()
            assert img.size == (2, 2)
            assert "exif" not in img.info and "xmp" not in img.info

    @patch("services.images.storage")
    def test_webp_keeps_orientation_and_drops_gps(
        self, mock_storage, client, photographer, library
    ):
        mock_storage.get_presigned_url.side_effect = lambda key: f"http://example.com/{key}"
        exif_bytes = piexif.dump(
            {
                "0th": {piexif.ImageIFD.Orientation: 6},
                "Exif": {piexif.ExifIFD.BodySerialNumber: b"SN-12345678"},
                "GPS": {
                    piexif.GPSIFD.GPSLatitude: ((48, 1), (12, 1), (0, 1)),
                    piexif.GPSIFD.GPSLatitudeRef: b"N",
                },
                "1st": {},
                "thumbnail": None,
            }
        )
        buf = io.BytesIO()
        PilImage.new("RGB", (8, 4), color="green").save(buf, format="WEBP", exif=exif_bytes)

        res = upload(client, library.id, make_token(photographer), buf.getvalue(), "p.webp", "image/webp")
        assert res.status_code == 201

        stored = mock_storage.upload_fileobj.call_args_list[0][0][0].read()
        assert b"SN-12345678" not in stored
        assert int.from_bytes(stored[4:8], "little") == len(stored) - 8
        with PilImage.open(io.BytesIO(stored)) as img:
            exif = piexif.load(img.info["exif"])
            assert exif["0th"][piexif.ImageIFD.Orientation] == 6
            assert exif["GPS"] == {}
            assert piexif.ExifIFD.BodySerialNumber not in exif["Exif"]
            # Same rotation as the watermark apply path (exif_transpose) sees
            assert ImageOps.exif_transpose(img).size == (4, 8)

    @patch("services.images.storage")
    def test_truncated_webp_rejected_fail_closed(
        self, mock_storage, client, photographer, library
    ):
        token = make_token(photographer)
        webp = make_webp_with_private_metadata()[:-6]

        res = upload(client, library.id, token, webp, "cut.webp", "image/webp")
        assert res.status_code == 415
        mock_storage.upload_fileobj.assert_not_called()


class TestWebpAlpha:
    @patch("services.images.storage")
    def test_rgba_webp_upload_accepted(
        self, mock_storage, client, photographer, library
    ):
        mock_storage.get_presigned_url.side_effect = lambda key: f"http://example.com/{key}"
        token = make_token(photographer)
        buf = io.BytesIO()
        PilImage.new("RGBA", (4, 4), color=(255, 0, 0, 100)).save(buf, format="WEBP")

        res = upload(client, library.id, token, buf.getvalue(), "alpha.webp", "image/webp")
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# GET /api/v1/libraries/<id>/images — pagination
# ---------------------------------------------------------------------------


from models import Image, CustomerState


def make_images(library, count):
    for i in range(count):
        db.session.add(
            Image(
                library_id=library.id,
                s3_key=f"img-{i}.jpg",
                original_filename=f"img-{i}.jpg",
                content_type="image/jpeg",
                size=1024,
                width=100,
                height=100,
                customer_state=CustomerState.none,
            )
        )
    db.session.commit()


class TestListImagesPagination:
    @patch("services.images.storage")
    def test_response_includes_pagination_fields(
        self, mock_storage, client, photographer, library
    ):
        mock_storage.get_presigned_url.return_value = "http://example.com/img"
        make_images(library, 3)
        token = make_token(photographer)
        data = client.get(
            f"/api/v1/libraries/{library.id}/images",
            headers=auth_header(token),
        ).get_json()
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "has_more" in data

    @patch("services.images.storage")
    def test_total_reflects_all_images(self, mock_storage, client, photographer, library):
        mock_storage.get_presigned_url.return_value = "http://example.com/img"
        make_images(library, 5)
        token = make_token(photographer)
        data = client.get(
            f"/api/v1/libraries/{library.id}/images",
            headers=auth_header(token),
        ).get_json()
        assert data["total"] == 5

    @patch("services.images.storage")
    def test_has_more_true_when_more_pages_exist(
        self, mock_storage, client, photographer, library
    ):
        mock_storage.get_presigned_url.return_value = "http://example.com/img"
        make_images(library, 5)
        token = make_token(photographer)
        data = client.get(
            f"/api/v1/libraries/{library.id}/images?page_size=3",
            headers=auth_header(token),
        ).get_json()
        assert data["has_more"] is True
        assert len(data["images"]) == 3

    @patch("services.images.storage")
    def test_has_more_false_when_all_fit(self, mock_storage, client, photographer, library):
        mock_storage.get_presigned_url.return_value = "http://example.com/img"
        make_images(library, 3)
        token = make_token(photographer)
        data = client.get(
            f"/api/v1/libraries/{library.id}/images?page_size=10",
            headers=auth_header(token),
        ).get_json()
        assert data["has_more"] is False

    @patch("services.images.storage")
    def test_page_2_returns_remaining_items(
        self, mock_storage, client, photographer, library
    ):
        mock_storage.get_presigned_url.return_value = "http://example.com/img"
        make_images(library, 5)
        token = make_token(photographer)
        data = client.get(
            f"/api/v1/libraries/{library.id}/images?page=2&page_size=3",
            headers=auth_header(token),
        ).get_json()
        assert len(data["images"]) == 2
        assert data["has_more"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/libraries/<id>/images — quota boundaries
# ---------------------------------------------------------------------------


from unittest.mock import PropertyMock


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


class TestListMedia:
    """GET /images returns photos and videos merged, newest first."""

    @staticmethod
    def _add_video(library, uuid, created_at, status):
        db.session.add(
            Video(
                uuid=uuid,
                library_id=library.id,
                s3_key=f"{uuid}.mp4",
                original_filename=f"{uuid}.mp4",
                content_type="video/mp4",
                size=2048,
                processing_status=status,
                created_at=created_at,
            )
        )

    @staticmethod
    def _add_image(library, name, created_at):
        db.session.add(
            Image(
                library_id=library.id,
                uuid=name,
                s3_key=f"{name}.jpg",
                original_filename=f"{name}.jpg",
                content_type="image/jpeg",
                size=1024,
                created_at=created_at,
            )
        )

    @pytest.fixture
    def mixed(self, library):
        t = lambda day: datetime(2026, 1, day, tzinfo=timezone.utc)
        self._add_image(library, "photo-old", t(1))
        self._add_video(library, "video-ready", t(2), VideoProcessingStatus.ready)
        self._add_image(library, "photo-new", t(3))
        self._add_video(library, "video-busy", t(4), VideoProcessingStatus.processing)
        db.session.commit()
        return library

    def _list(self, client, photographer, library, query=""):
        with patch("blueprints.api.images.storage") as st:
            st.get_presigned_url.side_effect = lambda key: f"http://s3/{key}"
            res = client.get(
                f"/api/v1/libraries/{library.id}/images{query}",
                headers=auth_header(make_token(photographer)),
            )
        return res

    def test_photos_and_videos_are_merged_newest_first(
        self, client, photographer, mixed
    ):
        res = self._list(client, photographer, mixed)

        assert res.status_code == 200
        body = res.get_json()
        assert body["total"] == 4
        assert [(i["media_type"], i["uuid"]) for i in body["images"]] == [
            ("video", "video-busy"),
            ("photo", "photo-new"),
            ("video", "video-ready"),
            ("photo", "photo-old"),
        ]

    def test_ready_video_has_presigned_urls(self, client, photographer, mixed):
        items = {i["uuid"]: i for i in self._list(client, photographer, mixed).get_json()["images"]}
        ready = db.session.execute(
            select(Video).where(Video.uuid == "video-ready")
        ).scalar_one()

        item = items["video-ready"]
        assert item["processing_status"] == "ready"
        assert item["original_url"] == f"http://s3/{ready.storage_path('originals')}"
        assert item["thumb_url"] == f"http://s3/{ready.storage_path('thumbs')}"

    def test_unfinished_video_has_no_urls(self, client, photographer, mixed):
        items = {i["uuid"]: i for i in self._list(client, photographer, mixed).get_json()["images"]}

        item = items["video-busy"]
        assert item["processing_status"] == "processing"
        assert item["original_url"] is None
        assert item["thumb_url"] is None

    def test_photo_keeps_all_three_urls(self, client, photographer, mixed):
        items = {i["uuid"]: i for i in self._list(client, photographer, mixed).get_json()["images"]}

        photo = items["photo-new"]
        assert photo["original_url"] and photo["preview_url"] and photo["thumb_url"]

    def test_pagination_spans_both_media_types(self, client, photographer, mixed):
        page1 = self._list(client, photographer, mixed, "?page_size=3").get_json()
        page2 = self._list(client, photographer, mixed, "?page_size=3&page=2").get_json()

        assert page1["has_more"] is True
        assert [i["uuid"] for i in page1["images"]] == [
            "video-busy",
            "photo-new",
            "video-ready",
        ]
        assert page2["has_more"] is False
        assert [i["uuid"] for i in page2["images"]] == ["photo-old"]

    def test_deleted_video_is_not_listed(self, client, photographer, mixed):
        video = db.session.execute(
            select(Video).where(Video.uuid == "video-ready")
        ).scalar_one()
        video.deleted_at = datetime.now(timezone.utc)
        db.session.commit()

        body = self._list(client, photographer, mixed).get_json()

        assert body["total"] == 3
        assert "video-ready" not in [i["uuid"] for i in body["images"]]


class TestUploadImageQuotas:
    def _upload(self, client, photographer, library):
        return upload(
            client, library.id, make_token(photographer), make_jpeg_bytes(), "a.jpg", "image/jpeg"
        )

    @patch("services.images.storage")
    def test_media_count_below_limit_allowed(self, _s, client, photographer, library):
        make_images(library, 2)
        with _patch_limits(media=3):
            res = self._upload(client, photographer, library)
        assert res.status_code == 201

    @patch("services.images.storage")
    def test_media_count_at_limit_rejected(self, _s, client, photographer, library):
        make_images(library, 3)
        with _patch_limits(media=3):
            res = self._upload(client, photographer, library)
        assert res.status_code == 422

    @patch("services.images.storage")
    def test_storage_exactly_at_limit_allowed(self, _s, client, photographer, library):
        size = len(make_jpeg_bytes())
        make_images(library, 1)  # 1024 bytes
        with _patch_limits(storage=1024 + size):
            res = self._upload(client, photographer, library)
        assert res.status_code == 201

    @patch("services.images.storage")
    def test_storage_one_byte_over_rejected(self, _s, client, photographer, library):
        size = len(make_jpeg_bytes())
        make_images(library, 1)
        with _patch_limits(storage=1024 + size - 1):
            res = self._upload(client, photographer, library)
        assert res.status_code == 422

    @patch("services.images.storage")
    def test_storage_overshoot_rejected(self, _s, client, photographer, library):
        make_images(library, 1)
        with _patch_limits(storage=1024 + 10):
            res = self._upload(client, photographer, library)
        assert res.status_code == 422
        assert res.get_json()["error"].endswith("for your subscription.")
