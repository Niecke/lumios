from flask import Blueprint, request, jsonify, g, current_app
from security import require_api_auth, require_api_role
from models import db, User, Library, Image
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
PREVIEW_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
WATERMARK_TEXT = "lumios.at"
WATERMARK_OPACITY = 80  # 0-255

# Magic byte signatures for allowed image formats
MAGIC_BYTES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}


PREVIEW_MAX_PX = 2048  # max longest side for preview before watermarking

# Exif IFD tags that identify the specific device or its owner and must be
# removed before storing the original file.
_PRIVATE_EXIF_TAGS = {
    piexif.ExifIFD.MakerNote,        # manufacturer data, often embeds serial numbers
    piexif.ExifIFD.CameraOwnerName,  # owner's name written by the camera
    piexif.ExifIFD.BodySerialNumber, # camera body serial number
    piexif.ExifIFD.LensSerialNumber, # lens serial number
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


def _create_watermarked_preview(pil_img: PilImage.Image) -> io.BytesIO:
    """Create a watermarked preview that fits under PREVIEW_MAX_BYTES."""
    # Downscale first to save memory
    w, h = pil_img.size
    ratio = min(PREVIEW_MAX_PX / w, PREVIEW_MAX_PX / h, 1.0)
    new_w, new_h = int(w * ratio), int(h * ratio)
    preview = pil_img.resize((new_w, new_h), PilImage.Resampling.LANCZOS).convert(
        "RGBA"
    )
    w, h = preview.size

    # Tile the pre-built watermark across the image
    tw, th = _WATERMARK_TILE.size
    for y in range(-th, h, th):
        for x in range(-tw, w, tw):
            preview.alpha_composite(_WATERMARK_TILE, dest=(x, y))

    preview = preview.convert("RGB")

    # Encode as JPEG, reduce quality if still over 2 MB
    for quality in (85, 70, 55):
        buf = io.BytesIO()
        preview.save(buf, format="JPEG", quality=quality)
        if buf.tell() <= PREVIEW_MAX_BYTES:
            buf.seek(0)
            preview.close()
            return buf

    buf.seek(0)
    preview.close()
    return buf


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
            "max_images_per_library": user.max_images_per_library if user else None,
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

    current_count = db.session.execute(
        select(db.func.count())
        .select_from(Image)
        .where(Image.library_id == library_id, Image.deleted_at.is_(None))
    ).scalar()

    if current_count >= user.max_images_per_library:
        return (
            jsonify(
                {
                    "error": f"Image limit reached ({user.max_images_per_library}) for this library."
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
    thumb_img = pil_img.copy()
    thumb_img.thumbnail((THUMB_SIZE, THUMB_SIZE))
    if thumb_img.mode in ("RGBA", "P", "LA"):
        thumb_img = thumb_img.convert("RGB")
    thumb_buf = io.BytesIO()
    thumb_img.save(thumb_buf, format="JPEG", quality=85)
    thumb_buf.seek(0)
    thumb_img.close()

    # Generate watermarked preview (max 2 MB)
    preview_buf = _create_watermarked_preview(pil_img)
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
    db.session.commit()
    return "", 204
