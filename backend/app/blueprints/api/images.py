from flask import Blueprint, request, jsonify, g, current_app
from security import require_api_auth, require_api_role
from models import db, User, Library, Image, AuditLogType
from services.audit import write_audit_log
from sqlalchemy import select
from datetime import datetime, timezone
import uuid as uuid_module
from PIL import Image as PilImage, ImageDraw, ImageFont, ImageOps
import io
import piexif
import tempfile
import os
from services import storage

images_api = Blueprint("images_api", __name__, url_prefix="/libraries")

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
THUMB_SIZE = 600  # longest side in pixels
PREVIEW_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
WATERMARK_TEXT = "lumios.niecke-it.de"
WATERMARK_OPACITY = 80  # 0-255
WATERMARK_LOGO_MAX_BYTES = 5 * 1024 * 1024  # 5 MB max for logo PNG uploads
WATERMARK_LOGO_MAGIC = b"\x89PNG\r\n\x1a\n"

# Magic byte signatures for allowed image formats
MAGIC_BYTES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}


PREVIEW_MAX_PX = 2048  # max longest side for preview before watermarking

# Exif IFD tags that identify the specific device or its owner and must be
# removed before storing the original file.
_PRIVATE_EXIF_TAGS = {
    piexif.ExifIFD.MakerNote,  # manufacturer data, often embeds serial numbers
    piexif.ExifIFD.CameraOwnerName,  # owner's name written by the camera
    piexif.ExifIFD.BodySerialNumber,  # camera body serial number
    piexif.ExifIFD.LensSerialNumber,  # lens serial number
}


def _strip_private_exif(file_data: bytes) -> bytes:
    """Remove privacy-sensitive EXIF data from a JPEG.

    Strips the GPS IFD entirely and removes individual Exif IFD tags that can
    identify the specific device or its owner (MakerNote, serial numbers,
    CameraOwnerName).  Camera settings and copyright tags are preserved.
    Returns the original bytes unchanged on any error.
    """
    try:
        exif_dict = piexif.load(file_data)
        exif_dict.pop("GPS", None)
        exif_ifd = exif_dict.get("Exif", {})
        for tag in _PRIVATE_EXIF_TAGS:
            exif_ifd.pop(tag, None)
        clean_exif = piexif.dump(exif_dict)
        # piexif.insert only accepts a file path, not raw bytes — use a temp file
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        try:
            os.write(fd, file_data)
            os.close(fd)
            piexif.insert(clean_exif, tmp_path)
            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            os.unlink(tmp_path)
    except Exception:
        return file_data  # malformed or missing EXIF — proceed with original


def _build_watermark_tile() -> PilImage.Image:
    """Build a small RGBA tile with the watermark pattern, created once at import."""
    font_size = 40
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
        )
    except OSError:
        font = ImageFont.load_default(size=font_size)

    # Measure text to determine tile size
    tmp = PilImage.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(tmp)
    bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tmp.close()

    # Tile covers one "cell" of the repeating pattern (two staggered rows)
    tile_w = text_w + font_size * 3
    tile_h = (text_h + font_size * 4) * 2
    tile = PilImage.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)

    # Row 1: aligned left
    y1 = font_size * 2
    draw.text(
        (0, y1), WATERMARK_TEXT, font=font, fill=(255, 255, 255, WATERMARK_OPACITY)
    )
    # Row 2: offset half a cell for staggered look
    y2 = y1 + text_h + font_size * 4
    draw.text(
        (tile_w // 2, y2),
        WATERMARK_TEXT,
        font=font,
        fill=(255, 255, 255, WATERMARK_OPACITY),
    )

    # Rotate the tile for diagonal appearance
    tile = tile.rotate(30, resample=PilImage.Resampling.BILINEAR, expand=True)
    return tile


_WATERMARK_TILE = _build_watermark_tile()

_PLACEHOLDER_W = 1200
_PLACEHOLDER_H = 800


def _build_placeholder_image() -> PilImage.Image:
    """Return a neutral gradient RGBA image used when no library photo is available.

    The image mimics a simple outdoor scene (sky gradient top-half, ground
    gradient bottom-half) so the watermark is visible against varied tones.
    """
    img = PilImage.new("RGBA", (_PLACEHOLDER_W, _PLACEHOLDER_H))
    pixels = img.load()
    assert pixels is not None
    sky_top = (135, 180, 220)
    sky_bottom = (195, 218, 235)
    ground_top = (120, 130, 100)
    ground_bottom = (80, 90, 65)
    mid = _PLACEHOLDER_H // 2
    for y in range(_PLACEHOLDER_H):
        if y < mid:
            t = y / max(mid - 1, 1)
            r = int(sky_top[0] + t * (sky_bottom[0] - sky_top[0]))
            g = int(sky_top[1] + t * (sky_bottom[1] - sky_top[1]))
            b = int(sky_top[2] + t * (sky_bottom[2] - sky_top[2]))
        else:
            t = (y - mid) / max(_PLACEHOLDER_H - mid - 1, 1)
            r = int(ground_top[0] + t * (ground_bottom[0] - ground_top[0]))
            g = int(ground_top[1] + t * (ground_bottom[1] - ground_top[1]))
            b = int(ground_top[2] + t * (ground_bottom[2] - ground_top[2]))
        for x in range(_PLACEHOLDER_W):
            pixels[x, y] = (r, g, b, 255)
    return img


def _apply_logo_watermark(
    preview: PilImage.Image,
    logo: PilImage.Image,
    logo_scale: float,
    logo_position: str,
) -> PilImage.Image:
    """Alpha-composite a logo onto the preview at the given position and scale.

    Only the logo pixels are affected; surrounding photo colors are unchanged.
    Returns the modified preview (RGBA).
    """
    img_w, img_h = preview.size
    logo_w = max(1, int(img_w * logo_scale))
    logo_h = max(1, int(logo.height * logo_w / logo.width))
    logo_resized = logo.resize((logo_w, logo_h), PilImage.Resampling.LANCZOS)

    margin = max(4, int(min(img_w, img_h) * 0.02))
    positions = {
        "bottom_right": (img_w - logo_w - margin, img_h - logo_h - margin),
        "bottom_left": (margin, img_h - logo_h - margin),
        "top_right": (img_w - logo_w - margin, margin),
        "top_left": (margin, margin),
        "center": ((img_w - logo_w) // 2, (img_h - logo_h) // 2),
    }
    x, y = positions.get(logo_position, positions["bottom_right"])
    # Clamp to image bounds
    x = max(0, min(x, img_w - logo_w))
    y = max(0, min(y, img_h - logo_h))

    preview.alpha_composite(logo_resized, dest=(x, y))
    logo_resized.close()
    return preview


def _create_watermarked_preview(
    pil_img: PilImage.Image,
    original_file_size: int,
    logo: PilImage.Image | None = None,
    logo_scale: float = 0.2,
    logo_position: str = "bottom_right",
) -> io.BytesIO:
    """Create a preview with watermark that fits under PREVIEW_MAX_BYTES.

    - If the original file is under PREVIEW_MAX_BYTES, the preview keeps its
      original dimensions (no resize). Quality starts at 95 for near-lossless output.
    - If the original file is PREVIEW_MAX_BYTES or larger, the image is downscaled
      progressively (10% steps) until the encoded JPEG fits under PREVIEW_MAX_BYTES.
    - Custom logo (RGBA PNG): composited cleanly — surrounding photo colors
      are unchanged. Fallback when logo is None: tiled semi-transparent text.
    - The ICC color profile is preserved so browsers render colors correctly.
    """
    w, h = pil_img.size
    icc_profile = pil_img.info.get("icc_profile")

    def _save_jpeg(img: PilImage.Image, quality: int) -> io.BytesIO:
        buf = io.BytesIO()
        save_kwargs: dict = {"format": "JPEG", "quality": quality}
        if icc_profile:
            save_kwargs["icc_profile"] = icc_profile
        img.save(buf, **save_kwargs)
        return buf

    if original_file_size < PREVIEW_MAX_BYTES:
        # Keep original resolution — just convert and apply watermark
        preview = pil_img.convert("RGBA")
        if logo is not None:
            preview = _apply_logo_watermark(preview, logo, logo_scale, logo_position)
        else:
            tw, th = _WATERMARK_TILE.size
            for ty in range(-th, h, th):
                for tx in range(-tw, w, tw):
                    preview.alpha_composite(_WATERMARK_TILE, dest=(tx, ty))
        preview = preview.convert("RGB")
        start_quality = 99
    else:
        # Downscale in 10% steps until the encoded JPEG fits under 5 MB
        best_buf: io.BytesIO | None = None
        for scale_pct in range(90, 30, -10):
            scale = scale_pct / 100.0
            new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
            candidate = pil_img.resize(
                (new_w, new_h), PilImage.Resampling.LANCZOS
            ).convert("RGBA")
            if logo is not None:
                candidate = _apply_logo_watermark(
                    candidate, logo, logo_scale, logo_position
                )
            else:
                tw, th = _WATERMARK_TILE.size
                for ty in range(-th, new_h, th):
                    for tx in range(-tw, new_w, tw):
                        candidate.alpha_composite(_WATERMARK_TILE, dest=(tx, ty))
            candidate_rgb = candidate.convert("RGB")
            candidate.close()
            buf = _save_jpeg(candidate_rgb, quality=90)
            candidate_rgb.close()
            if buf.tell() <= PREVIEW_MAX_BYTES:
                buf.seek(0)
                return buf
            best_buf = buf  # keep last attempt as fallback
        if best_buf is not None:
            best_buf.seek(0)
            return best_buf
        # Extremely large image — fall through with full size at low quality
        preview = pil_img.convert("RGBA")
        if logo is not None:
            preview = _apply_logo_watermark(preview, logo, logo_scale, logo_position)
        preview = preview.convert("RGB")
        start_quality = 60

    for quality in (start_quality, 80, 70, 60):
        buf = _save_jpeg(preview, quality=quality)
        if buf.tell() <= PREVIEW_MAX_BYTES:
            buf.seek(0)
            preview.close()
            return buf

    buf.seek(0)
    preview.close()
    return buf


def _load_library_logo(library: "Library") -> PilImage.Image | None:
    """Download the library's watermark logo from GCS and return it as RGBA.

    Returns None if no logo is configured or if loading fails.
    """
    if not library.watermark_gcs_key:
        return None
    try:
        data = storage.get_object_bytes(library.watermark_gcs_key)
        return PilImage.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        current_app.logger.warning(
            "Failed to load watermark logo for library %s", library.id
        )
        return None


def _get_library(library_id: int, user_id: int) -> Library | None:
    return db.session.execute(
        select(Library).where(
            Library.id == library_id,
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


@images_api.route("/<int:library_id>/images", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def list_images(library_id: int):
    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    user = db.session.get(User, user_id)
    images = (
        db.session.execute(
            select(Image)
            .where(Image.library_id == library_id, Image.deleted_at.is_(None))
            .order_by(Image.created_at.desc())
        )
        .scalars()
        .all()
    )

    image_dicts = [
        img.to_dict(
            original_url=storage.get_presigned_url(img.storage_path("originals")),
            preview_url=storage.get_presigned_url(img.storage_path("previews")),
            thumb_url=storage.get_presigned_url(img.storage_path("thumbs")),
        )
        for img in images
    ]

    return jsonify(
        {
            "images": image_dicts,
            "count": len(image_dicts),
            "max_images_per_library": (
                user.effective_limits["max_images_per_library"] if user else None
            ),
        }
    )


@images_api.route("/<int:library_id>/images", methods=["POST"])
@require_api_auth
@require_api_role("photographer")
def upload_image(library_id: int):
    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "User not found"}), 404

    limits = user.effective_limits

    current_count = db.session.execute(
        select(db.func.count())
        .select_from(Image)
        .where(Image.library_id == library_id, Image.deleted_at.is_(None))
    ).scalar()

    if current_count >= limits["max_images_per_library"]:
        return (
            jsonify(
                {
                    "error": f"Image limit reached ({limits['max_images_per_library']}) for this library."
                }
            ),
            422,
        )

    storage_used = db.session.execute(
        select(db.func.coalesce(db.func.sum(Image.size), 0))
        .join(Image.library)
        .where(
            Library.user_id == user_id,
            Image.deleted_at.is_(None),
            Library.deleted_at.is_(None),
        )
    ).scalar()

    if storage_used >= limits["max_storage_bytes"]:
        limit_mb = limits["max_storage_bytes"] // (1024 * 1024)
        return (
            jsonify(
                {
                    "error": f"Storage limit reached ({limit_mb} MB) for your subscription."
                }
            ),
            422,
        )

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    content_type = file.content_type or ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        return jsonify({"error": "Only JPEG and PNG images are allowed"}), 415

    file_data = file.read()
    if len(file_data) > MAX_FILE_SIZE:
        return jsonify({"error": "File too large (max 20 MB)"}), 413

    # Verify magic bytes match the claimed content type
    expected_magic = MAGIC_BYTES[content_type]
    if not file_data.startswith(expected_magic):
        return jsonify({"error": "File content does not match its declared type"}), 415

    # Pillow must be able to open the file — reject corrupt or disguised uploads
    try:
        pil_img = PilImage.open(io.BytesIO(file_data))
        pil_img = ImageOps.exif_transpose(pil_img)
        width, height = pil_img.size
    except Exception:
        current_app.logger.exception(
            "Uploaded file is not a valid image: %s", file.filename
        )
        return jsonify({"error": "File is not a valid image"}), 415

    # Generate 300px thumbnail
    icc_profile = pil_img.info.get("icc_profile")
    thumb_img = pil_img.copy()
    thumb_img.thumbnail((THUMB_SIZE, THUMB_SIZE))
    if thumb_img.mode in ("RGBA", "P", "LA"):
        thumb_img = thumb_img.convert("RGB")
    thumb_buf = io.BytesIO()
    thumb_save_kwargs: dict = {"format": "JPEG", "quality": 85}
    if icc_profile:
        thumb_save_kwargs["icc_profile"] = icc_profile
    thumb_img.save(thumb_buf, **thumb_save_kwargs)
    thumb_buf.seek(0)
    thumb_img.close()

    # Generate watermarked preview (max 5 MB)
    logo = _load_library_logo(library)
    preview_buf = _create_watermarked_preview(
        pil_img,
        original_file_size=len(file_data),
        logo=logo,
        logo_scale=library.watermark_scale or 0.2,
        logo_position=library.watermark_position or "bottom_right",
    )
    if logo is not None:
        logo.close()
    pil_img.close()

    if content_type == "image/jpeg":
        file_data = _strip_private_exif(file_data)

    ext = "jpg" if content_type == "image/jpeg" else "png"
    photo_uuid = str(uuid_module.uuid4())
    s3_key = f"{photo_uuid}.{ext}"

    image = Image(
        uuid=photo_uuid,
        library_id=library_id,
        s3_key=s3_key,
        original_filename=file.filename,
        content_type=content_type,
        size=len(file_data),
        width=width,
        height=height,
    )

    base_path = f"photos/{user_id}/{library_id}"
    original_path = f"{base_path}/originals/{s3_key}"
    preview_path = f"{base_path}/previews/{s3_key}"
    thumb_path = f"{base_path}/thumbs/{s3_key}"
    try:
        storage.ensure_bucket()
        storage.upload_fileobj(io.BytesIO(file_data), original_path, content_type)
        storage.upload_fileobj(preview_buf, preview_path, "image/jpeg")
        storage.upload_fileobj(thumb_buf, thumb_path, "image/jpeg")
    except Exception:
        current_app.logger.exception(
            "GCS upload failed for key=%s bucket=%s endpoint=%s",
            original_path,
            storage.S3_BUCKET,
            storage.S3_ENDPOINT_URL,
        )
        return jsonify({"error": "Storage error. Please try again."}), 502

    db.session.add(image)
    db.session.flush()
    write_audit_log(
        AuditLogType.picture_uploaded,
        creator_id=user_id,
        related_object_type="image",
        related_object_id=image.uuid,
    )
    db.session.commit()

    original_url = storage.get_presigned_url(original_path)
    preview_url = storage.get_presigned_url(preview_path)
    thumb_url = storage.get_presigned_url(thumb_path)
    return (
        jsonify(
            image.to_dict(
                original_url=original_url,
                preview_url=preview_url,
                thumb_url=thumb_url,
            )
        ),
        201,
    )


@images_api.route("/<int:library_id>/images/<int:image_id>", methods=["DELETE"])
@require_api_auth
@require_api_role("photographer")
def delete_image(library_id: int, image_id: int):
    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    image = db.session.execute(
        select(Image).where(
            Image.id == image_id,
            Image.library_id == library_id,
            Image.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if image is None:
        return jsonify({"error": "Image not found"}), 404

    image.deleted_at = datetime.now(timezone.utc)
    write_audit_log(
        AuditLogType.picture_deleted,
        creator_id=user_id,
        related_object_type="image",
        related_object_id=image.uuid,
    )
    db.session.commit()
    return "", 204
