"""
Tests for watermark endpoints:
  POST   /api/v1/libraries/<id>/watermark        upload PNG logo
  DELETE /api/v1/libraries/<id>/watermark        remove logo
  GET    /api/v1/libraries/<id>/watermark/preview live preview JPEG
  POST   /api/v1/libraries/<id>/watermark/apply  re-render all previews
  PATCH  /api/v1/libraries/<id>                  watermark_scale / watermark_position

Also covers:
  _create_watermarked_preview() with and without logo
"""

import io
from datetime import datetime
from unittest.mock import patch

import pytest
from PIL import Image as PilImage

from models import db, User, Role, Library, Image, SubscriptionType
from services.token import create_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def make_token(user: User) -> str:
    return create_token(user.id, user.email, [r.name for r in user.roles])


def make_png_bytes(width: int = 4, height: int = 4, mode: str = "RGBA") -> bytes:
    buf = io.BytesIO()
    img = PilImage.new(mode, (width, height), color=(255, 0, 0, 200))
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_jpeg_bytes(width: int = 8, height: int = 6) -> bytes:
    buf = io.BytesIO()
    img = PilImage.new("RGB", (width, height), color=(100, 150, 200))
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def upload_logo(client, library_id, token, data, content_type="image/png"):
    return client.post(
        f"/api/v1/libraries/{library_id}/watermark",
        data={"file": (io.BytesIO(data), "logo.png", content_type)},
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
    user = User(
        email="photo@test.com",
        active=True,
        max_libraries=10,
        subscription=SubscriptionType.premium,
    )
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


@pytest.fixture
def library_with_image(library, photographer):
    """Library that already has one image (needed for the preview endpoint)."""
    img = Image(
        library_id=library.id,
        s3_key="test-uuid.jpg",
        original_filename="test.jpg",
        content_type="image/jpeg",
        size=1000,
        width=8,
        height=6,
    )
    db.session.add(img)
    db.session.commit()
    return library


# ---------------------------------------------------------------------------
# POST /watermark — upload logo
# ---------------------------------------------------------------------------


class TestUploadWatermark:

    @patch("blueprints.api.libraries.storage")
    def test_accepts_valid_png(self, mock_storage, client, photographer, library):
        mock_storage.get_presigned_url.return_value = "http://example.com/logo"
        token = make_token(photographer)
        res = upload_logo(client, library.id, token, make_png_bytes())
        assert res.status_code == 200
        data = res.get_json()
        assert data["watermark_gcs_key"] == f"watermarks/{photographer.id}/{library.id}/watermark.png"
        assert data["watermark_scale"] == 0.2
        assert data["watermark_position"] == "bottom_right"
        mock_storage.upload_fileobj.assert_called_once()

    @patch("blueprints.api.libraries.storage")
    def test_preserves_existing_scale_and_position(self, mock_storage, client, photographer, library):
        """If scale/position are already set, uploading a new logo keeps them."""
        library.watermark_scale = 0.35
        library.watermark_position = "top_left"
        db.session.commit()
        token = make_token(photographer)
        res = upload_logo(client, library.id, token, make_png_bytes())
        assert res.status_code == 200
        data = res.get_json()
        assert data["watermark_scale"] == 0.35
        assert data["watermark_position"] == "top_left"

    def test_rejects_jpeg_as_watermark(self, client, photographer, library):
        token = make_token(photographer)
        res = upload_logo(client, library.id, token, make_jpeg_bytes(), content_type="image/jpeg")
        assert res.status_code == 415
        assert "PNG" in res.get_json()["error"]

    def test_rejects_wrong_magic_bytes(self, client, photographer, library):
        token = make_token(photographer)
        # Claim PNG but send JPEG bytes
        res = upload_logo(client, library.id, token, make_jpeg_bytes(), content_type="image/png")
        assert res.status_code == 415
        assert "does not match" in res.get_json()["error"]

    def test_rejects_no_file(self, client, photographer, library):
        token = make_token(photographer)
        res = client.post(
            f"/api/v1/libraries/{library.id}/watermark",
            headers=auth_header(token),
            content_type="multipart/form-data",
        )
        assert res.status_code == 400

    def test_requires_auth(self, client, library):
        res = upload_logo(client, library.id, "badtoken", make_png_bytes())
        assert res.status_code == 401

    def test_returns_404_for_wrong_library(self, client, photographer):
        token = make_token(photographer)
        res = upload_logo(client, 9999, token, make_png_bytes())
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /watermark — remove logo
# ---------------------------------------------------------------------------


class TestDeleteWatermark:

    @patch("blueprints.api.libraries.storage")
    def test_clears_watermark_key(self, mock_storage, client, photographer, library):
        library.watermark_gcs_key = f"watermarks/{photographer.id}/{library.id}/watermark.png"
        db.session.commit()
        token = make_token(photographer)
        res = client.delete(
            f"/api/v1/libraries/{library.id}/watermark",
            headers=auth_header(token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["watermark_gcs_key"] is None
        mock_storage.delete_object.assert_called_once()

    @patch("blueprints.api.libraries.storage")
    def test_idempotent_when_no_logo_set(self, mock_storage, client, photographer, library):
        token = make_token(photographer)
        res = client.delete(
            f"/api/v1/libraries/{library.id}/watermark",
            headers=auth_header(token),
        )
        assert res.status_code == 200
        mock_storage.delete_object.assert_not_called()

    def test_requires_auth(self, client, library):
        res = client.delete(
            f"/api/v1/libraries/{library.id}/watermark",
            headers=auth_header("badtoken"),
        )
        assert res.status_code == 401


# ---------------------------------------------------------------------------
# GET /watermark/preview — live preview JPEG
# ---------------------------------------------------------------------------


class TestWatermarkPreview:

    def test_returns_400_when_no_logo(self, client, photographer, library):
        token = make_token(photographer)
        res = client.get(
            f"/api/v1/libraries/{library.id}/watermark/preview",
            headers=auth_header(token),
        )
        assert res.status_code == 400
        assert "No watermark" in res.get_json()["error"]

    @patch("services.images.storage")
    def test_returns_jpeg_with_placeholder_when_no_photos(self, mock_img_storage, client, photographer, library):
        """No photos in library → placeholder image is used; preview is still returned."""
        library.watermark_gcs_key = "watermarks/1/1/watermark.png"
        db.session.commit()
        mock_img_storage.get_object_bytes.return_value = make_png_bytes()
        token = make_token(photographer)
        res = client.get(
            f"/api/v1/libraries/{library.id}/watermark/preview",
            headers=auth_header(token),
        )
        assert res.status_code == 200
        assert res.content_type == "image/jpeg"
        assert len(res.data) > 0

    @patch("services.images.storage")
    @patch("blueprints.api.libraries.storage")
    def test_returns_jpeg(self, mock_lib_storage, mock_img_storage, client, photographer, library_with_image):
        library_with_image.watermark_gcs_key = f"watermarks/{photographer.id}/{library_with_image.id}/watermark.png"
        db.session.commit()

        def get_bytes(key: str) -> bytes:
            return make_png_bytes() if "watermarks" in key else make_jpeg_bytes()

        mock_lib_storage.get_object_bytes.side_effect = get_bytes
        mock_img_storage.get_object_bytes.side_effect = get_bytes
        token = make_token(photographer)
        res = client.get(
            f"/api/v1/libraries/{library_with_image.id}/watermark/preview",
            query_string={"scale": "0.2", "position": "bottom_right"},
            headers=auth_header(token),
        )
        assert res.status_code == 200
        assert res.content_type == "image/jpeg"
        assert len(res.data) > 0

    @patch("blueprints.api.libraries.storage")
    def test_rejects_invalid_position(self, mock_storage, client, photographer, library_with_image):
        library_with_image.watermark_gcs_key = "watermarks/x/y/watermark.png"
        db.session.commit()
        token = make_token(photographer)
        res = client.get(
            f"/api/v1/libraries/{library_with_image.id}/watermark/preview",
            query_string={"scale": "0.2", "position": "diagonal"},
            headers=auth_header(token),
        )
        assert res.status_code == 400

    def test_requires_auth(self, client, library):
        res = client.get(
            f"/api/v1/libraries/{library.id}/watermark/preview",
            headers=auth_header("badtoken"),
        )
        assert res.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /libraries/<id> — watermark_scale and watermark_position
# ---------------------------------------------------------------------------


class TestPatchWatermarkConfig:

    def test_sets_watermark_scale(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(
            f"/api/v1/libraries/{library.id}",
            json={"watermark_scale": 0.3},
            headers=auth_header(token),
        )
        assert res.status_code == 200
        assert res.get_json()["watermark_scale"] == pytest.approx(0.3)

    def test_sets_watermark_position(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(
            f"/api/v1/libraries/{library.id}",
            json={"watermark_position": "top_left"},
            headers=auth_header(token),
        )
        assert res.status_code == 200
        assert res.get_json()["watermark_position"] == "top_left"

    def test_rejects_scale_out_of_range(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(
            f"/api/v1/libraries/{library.id}",
            json={"watermark_scale": 0.99},
            headers=auth_header(token),
        )
        assert res.status_code == 400
        assert "watermark_scale" in res.get_json()["error"]

    def test_rejects_scale_too_small(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(
            f"/api/v1/libraries/{library.id}",
            json={"watermark_scale": 0.01},
            headers=auth_header(token),
        )
        assert res.status_code == 400

    def test_rejects_invalid_position(self, client, photographer, library):
        token = make_token(photographer)
        res = client.patch(
            f"/api/v1/libraries/{library.id}",
            json={"watermark_position": "somewhere_random"},
            headers=auth_header(token),
        )
        assert res.status_code == 400
        assert "watermark_position" in res.get_json()["error"]

    def test_accepts_all_valid_positions(self, client, photographer, library):
        token = make_token(photographer)
        for pos in ("bottom_right", "bottom_left", "top_right", "top_left", "center"):
            res = client.patch(
                f"/api/v1/libraries/{library.id}",
                json={"watermark_position": pos},
                headers=auth_header(token),
            )
            assert res.status_code == 200, f"Position {pos!r} should be accepted"


# ---------------------------------------------------------------------------
# _create_watermarked_preview() — image processing unit tests
# ---------------------------------------------------------------------------


class TestCreateWatermarkedPreview:

    def test_fallback_text_watermark_produces_valid_jpeg(self):
        from services.images import _create_watermarked_preview

        pil_img = PilImage.new("RGB", (100, 80), color=(50, 100, 150))
        buf = _create_watermarked_preview(pil_img, original_file_size=100)
        assert buf.read(3) == b"\xff\xd8\xff"  # JPEG magic bytes

    def test_logo_watermark_produces_valid_jpeg(self):
        from services.images import _create_watermarked_preview

        pil_img = PilImage.new("RGB", (200, 150), color=(50, 100, 150))
        logo = PilImage.new("RGBA", (20, 20), color=(255, 0, 0, 200))
        buf = _create_watermarked_preview(
            pil_img, original_file_size=100, logo=logo, logo_scale=0.2, logo_position="bottom_right"
        )
        assert buf.read(3) == b"\xff\xd8\xff"

    def test_large_file_stays_under_5mb(self):
        from services.images import _create_watermarked_preview, PREVIEW_MAX_BYTES

        # Create a large image (500x400) and report a large file size to trigger resize
        pil_img = PilImage.new("RGB", (500, 400), color=(120, 80, 60))
        large_size = 6 * 1024 * 1024  # 6 MB — triggers downscale branch
        buf = _create_watermarked_preview(pil_img, original_file_size=large_size)
        buf.seek(0, 2)
        assert buf.tell() <= PREVIEW_MAX_BYTES

    def test_logo_composited_at_all_positions(self):
        from services.images import _create_watermarked_preview

        pil_img = PilImage.new("RGB", (200, 150))
        logo = PilImage.new("RGBA", (10, 10), color=(0, 255, 0, 255))
        for position in ("bottom_right", "bottom_left", "top_right", "top_left", "center"):
            buf = _create_watermarked_preview(
                pil_img, original_file_size=100, logo=logo, logo_scale=0.1, logo_position=position
            )
            assert buf.read(3) == b"\xff\xd8\xff", f"Failed for position={position}"


# ---------------------------------------------------------------------------
# POST /watermark/apply — re-render all image previews
# ---------------------------------------------------------------------------


class TestApplyWatermark:

    @patch("services.images.storage")
    @patch("blueprints.api.libraries.storage")
    def test_applies_watermark_to_all_images(
        self, mock_lib_storage, mock_img_storage, client, photographer, library
    ):
        library.watermark_gcs_key = f"watermarks/{photographer.id}/{library.id}/watermark.png"
        library.watermark_scale = 0.2
        library.watermark_position = "bottom_right"
        img1 = Image(
            library_id=library.id,
            s3_key="img1.jpg",
            original_filename="photo1.jpg",
            content_type="image/jpeg",
            size=1000,
            width=8,
            height=6,
        )
        img2 = Image(
            library_id=library.id,
            s3_key="img2.jpg",
            original_filename="photo2.jpg",
            content_type="image/jpeg",
            size=1000,
            width=8,
            height=6,
        )
        db.session.add_all([img1, img2])
        db.session.commit()

        mock_img_storage.get_object_bytes.return_value = make_png_bytes()
        mock_lib_storage.get_object_bytes.return_value = make_jpeg_bytes()
        token = make_token(photographer)
        res = client.post(
            f"/api/v1/libraries/{library.id}/watermark/apply",
            headers=auth_header(token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["updated"] == 2
        assert data["failed"] == 0
        assert data["total"] == 2
        assert mock_lib_storage.upload_fileobj.call_count == 2

    def test_requires_auth(self, client, library):
        res = client.post(
            f"/api/v1/libraries/{library.id}/watermark/apply",
            headers=auth_header("badtoken"),
        )
        assert res.status_code == 401

    def test_returns_404_for_wrong_library(self, client, photographer):
        token = make_token(photographer)
        res = client.post(
            "/api/v1/libraries/9999/watermark/apply",
            headers=auth_header(token),
        )
        assert res.status_code == 404

    @patch("blueprints.api.libraries.storage")
    def test_returns_zero_for_empty_library(
        self, mock_storage, client, photographer, library
    ):
        library.watermark_gcs_key = f"watermarks/{photographer.id}/{library.id}/watermark.png"
        db.session.commit()
        token = make_token(photographer)
        res = client.post(
            f"/api/v1/libraries/{library.id}/watermark/apply",
            headers=auth_header(token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["updated"] == 0
        assert data["failed"] == 0
        assert data["total"] == 0

    @patch("services.images.storage")
    @patch("blueprints.api.libraries.storage")
    def test_skips_deleted_images(
        self, mock_lib_storage, mock_img_storage, client, photographer, library
    ):
        library.watermark_gcs_key = f"watermarks/{photographer.id}/{library.id}/watermark.png"
        active_img = Image(
            library_id=library.id,
            s3_key="active.jpg",
            original_filename="active.jpg",
            content_type="image/jpeg",
            size=1000,
            width=8,
            height=6,
        )
        deleted_img = Image(
            library_id=library.id,
            s3_key="deleted.jpg",
            original_filename="deleted.jpg",
            content_type="image/jpeg",
            size=1000,
            width=8,
            height=6,
            deleted_at=datetime(2025, 1, 1),
        )
        db.session.add_all([active_img, deleted_img])
        db.session.commit()

        mock_img_storage.get_object_bytes.return_value = make_png_bytes()
        mock_lib_storage.get_object_bytes.return_value = make_jpeg_bytes()
        token = make_token(photographer)
        res = client.post(
            f"/api/v1/libraries/{library.id}/watermark/apply",
            headers=auth_header(token),
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["updated"] == 1
        assert data["failed"] == 0
        assert data["total"] == 1
