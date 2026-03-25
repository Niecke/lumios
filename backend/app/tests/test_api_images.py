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
from PIL import Image as PilImage

from models import db, User, Role, Library
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
    role = Role(name="photographer", description="Photographer")
    db.session.add(role)
    db.session.commit()
    return role


@pytest.fixture
def photographer(photographer_role):
    user = User(email="photo@test.com", active=True, max_libraries=5)
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
        assert "Only JPEG and PNG" in res.get_json()["error"]

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

    @patch("blueprints.api.images.storage")
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

    @patch("blueprints.api.images.storage")
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


class TestExifStripping:
    """GPS and device-identifying EXIF tags must be removed from JPEG originals."""

    @patch("blueprints.api.images.storage")
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
