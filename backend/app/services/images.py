"""Image processing service — shared between authenticated and public upload paths."""

from __future__ import annotations

import io
import os
import tempfile
import uuid as uuid_module

from flask import current_app
from PIL import Image as PilImage, ImageDraw, ImageFont, ImageOps

import piexif

from models import db, Image, AuditLogType
from services.audit import write_audit_log
from services import storage
from services.redis_client import cache_delete, cache_delete_pattern

# Type-only imports to avoid circular dependency at runtime
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from models import Library, User

_DEJAVU_FONT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fonts", "DejaVuSans-Bold.ttf",
)

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

# Exif IFD tags that identify the specific device or its owner
_PRIVATE_EXIF_TAGS = {
    piexif.ExifIFD.MakerNote,
    piexif.ExifIFD.CameraOwnerName,
    piexif.ExifIFD.BodySerialNumber,
    piexif.ExifIFD.LensSerialNumber,
}


def validate_upload(file_data: bytes, content_type: str, filename: str) -> None:
    """Raise ValueError with a user-facing message on any rejection."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError("Only JPEG and PNG images are allowed")
    if len(file_data) > MAX_FILE_SIZE:
        raise ValueError("File too large (max 20 MB)")
    expected_magic = MAGIC_BYTES[content_type]
    if not file_data.startswith(expected_magic):
        raise ValueError("File content does not match its declared type")
    try:
        img = PilImage.open(io.BytesIO(file_data))
        img.verify()
    except Exception:
        raise ValueError("File is not a valid image")


def _strip_private_exif(file_data: bytes) -> bytes:
    """Remove privacy-sensitive EXIF data from a JPEG."""
    try:
        exif_dict = piexif.load(file_data)
        exif_dict.pop("GPS", None)
        exif_ifd = exif_dict.get("Exif", {})
        for tag in _PRIVATE_EXIF_TAGS:
            exif_ifd.pop(tag, None)
        clean_exif = piexif.dump(exif_dict)
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
        return file_data


def _build_watermark_tile() -> PilImage.Image:
    """Build a small RGBA tile with the watermark pattern, created once at import."""
    font_size = 40
    try:
        font = ImageFont.truetype(_DEJAVU_FONT, font_size)
    except OSError:
        font = ImageFont.load_default(size=font_size)

    tmp = PilImage.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(tmp)
    bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tmp.close()

    tile_w = text_w + font_size * 3
    tile_h = (text_h + font_size * 4) * 2
    tile = PilImage.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)

    y1 = font_size * 2
    draw.text(
        (0, y1), WATERMARK_TEXT, font=font, fill=(255, 255, 255, WATERMARK_OPACITY)
    )
    y2 = y1 + text_h + font_size * 4
    draw.text(
        (tile_w // 2, y2),
        WATERMARK_TEXT,
        font=font,
        fill=(255, 255, 255, WATERMARK_OPACITY),
    )

    tile = tile.rotate(30, resample=PilImage.Resampling.BILINEAR, expand=True)
    return tile


_WATERMARK_TILE = _build_watermark_tile()

_PLACEHOLDER_W = 1200
_PLACEHOLDER_H = 800


def _build_placeholder_image() -> PilImage.Image:
    """Return a neutral gradient RGBA image used when no library photo is available."""
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
    """Alpha-composite a logo onto the preview at the given position and scale."""
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
    """Create a preview with watermark that fits under PREVIEW_MAX_BYTES."""
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
            best_buf = buf
        if best_buf is not None:
            best_buf.seek(0)
            return best_buf
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
    """Download the library's watermark logo from GCS and return it as RGBA."""
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


def process_and_store_image(
    library: "Library",
    owner: "User",
    file_data: bytes,
    filename: str,
    content_type: str,
    is_external: bool = False,
) -> Image:
    """Process an image upload and persist to S3 + DB.

    S3 path always uses owner.id (photographer). Raises ValueError on validation
    failure, propagates storage exceptions.
    """
    pil_img = PilImage.open(io.BytesIO(file_data))
    pil_img = ImageOps.exif_transpose(pil_img)
    width, height = pil_img.size

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

    base_path = f"photos/{owner.id}/{library.id}"
    original_path = f"{base_path}/originals/{s3_key}"
    preview_path = f"{base_path}/previews/{s3_key}"
    thumb_path = f"{base_path}/thumbs/{s3_key}"

    storage.ensure_bucket()
    storage.upload_fileobj(io.BytesIO(file_data), original_path, content_type)
    storage.upload_fileobj(preview_buf, preview_path, "image/jpeg")
    storage.upload_fileobj(thumb_buf, thumb_path, "image/jpeg")

    image = Image(
        uuid=photo_uuid,
        library_id=library.id,
        s3_key=s3_key,
        original_filename=filename,
        content_type=content_type,
        size=len(file_data),
        width=width,
        height=height,
        is_external=is_external,
    )
    db.session.add(image)
    db.session.flush()

    write_audit_log(
        AuditLogType.picture_uploaded,
        creator_id=None if is_external else owner.id,
        related_object_type="image",
        related_object_id=image.uuid,
    )
    db.session.commit()
    cache_delete_pattern(f"public:library:{library.uuid}:*")
    cache_delete(f"user:storage:{owner.id}")
    return image
