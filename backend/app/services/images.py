"""Image processing service — shared between authenticated and public upload paths."""

from __future__ import annotations

import io
import os
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

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
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
    "image/webp": b"RIFF",
}

# File extension per allowed content type
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

PREVIEW_MAX_PX = 2048  # max longest side for preview before watermarking

def invalidate_watermark_previews(library_id: int) -> None:
    """Drop all cached watermark previews (and their index) of a library."""
    cache_delete_pattern(f"watermark_preview:{library_id}:*")


def validate_upload(file_data: bytes, content_type: str) -> None:
    """Raise ValueError with a user-facing message on any rejection."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError("Only JPEG, PNG, and WebP images are allowed")
    if len(file_data) > MAX_FILE_SIZE:
        raise ValueError("File too large (max 20 MB)")
    expected_magic = MAGIC_BYTES[content_type]
    if not file_data.startswith(expected_magic):
        raise ValueError("File content does not match its declared type")
    if content_type == "image/webp" and file_data[8:12] != b"WEBP":
        raise ValueError("File content does not match its declared type")
    try:
        img = PilImage.open(io.BytesIO(file_data))
        img.verify()
    except Exception:
        raise ValueError("File is not a valid image")
    if content_type in ("image/jpeg", "image/webp"):
        # Fail closed: an image whose metadata cannot be removed is not stored
        strip = _strip_jpeg_metadata if content_type == "image/jpeg" else _strip_webp_metadata
        try:
            strip(file_data)
        except ValueError:
            raise ValueError("File is not a valid image")


# JPEG markers kept as they are needed to render the image: SOF0-3/5-7/9-11/13-15,
# DHT, DAC, DQT, DNL, DRI, EXP, APP0 (JFIF) and APP14 (Adobe colour transform)
_JPEG_KEEP_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    | {0xC4, 0xCC, 0xDB, 0xDC, 0xDD, 0xDF, 0xE0, 0xEE}
)
_JPEG_APP1 = 0xE1
_JPEG_APP2 = 0xE2
_JPEG_SOS = 0xDA
_JPEG_EOI = 0xD9


def _strip_jpeg_metadata(file_data: bytes) -> bytes:
    """Rewrite a JPEG with an allowlist of segments, keeping only the EXIF Orientation.

    Kept: image structure segments, JFIF (APP0), ICC profile (APP2), Adobe (APP14)
    and an EXIF APP1 holding only the Orientation tag. Everything else (other EXIF
    data, thumbnail, XMP, IPTC, comments, other APPn) is dropped.

    Raises ValueError when the segment structure cannot be parsed, so the caller
    rejects the upload instead of storing metadata unchanged.
    """
    n = len(file_data)
    if n < 4 or file_data[:2] != b"\xff\xd8" or file_data[-2:] != b"\xff\xd9":
        raise ValueError("Not a complete JPEG file")

    out = [b"\xff\xd8"]
    pos = 2
    seen_sos = False
    while True:
        if pos + 2 > n or file_data[pos] != 0xFF:
            raise ValueError("Malformed JPEG marker")
        while pos + 1 < n and file_data[pos + 1] == 0xFF:  # fill bytes
            pos += 1
        if pos + 2 > n:
            raise ValueError("Malformed JPEG marker")
        marker = file_data[pos + 1]
        pos += 2
        if marker == _JPEG_EOI:
            if pos != n or not seen_sos:
                raise ValueError("Unexpected end of JPEG")
            out.append(b"\xff\xd9")
            return b"".join(out)
        if marker in (0x00, 0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            raise ValueError("Unexpected JPEG marker")
        if pos + 2 > n:
            raise ValueError("Truncated JPEG segment")
        length = int.from_bytes(file_data[pos:pos + 2], "big")
        end = pos + length
        if length < 2 or end > n:
            raise ValueError("Malformed JPEG segment length")
        payload = file_data[pos + 2:end]

        if marker == _JPEG_SOS:
            # Header and entropy-coded data up to the next real marker, verbatim
            scan_end = end
            while True:
                idx = file_data.find(b"\xff", scan_end)
                if idx == -1 or idx + 1 >= n:
                    raise ValueError("Truncated JPEG scan")
                nxt = file_data[idx + 1]
                if nxt == 0x00 or 0xD0 <= nxt <= 0xD7:
                    scan_end = idx + 2
                    continue
                scan_end = idx
                break
            out.append(file_data[pos - 2:scan_end])
            seen_sos = True
            pos = scan_end
            continue

        if marker in _JPEG_KEEP_MARKERS:
            out.append(file_data[pos - 2:end])
        elif marker == _JPEG_APP2 and payload.startswith(b"ICC_PROFILE\x00"):
            out.append(file_data[pos - 2:end])
        elif marker == _JPEG_APP1 and payload.startswith(b"Exif\x00\x00"):
            kept = _orientation_only_exif(payload[6:])
            if kept is not None:
                body = b"Exif\x00\x00" + kept
                out.append(b"\xff\xe1" + (len(body) + 2).to_bytes(2, "big") + body)
        pos = end


_WEBP_METADATA_CHUNKS = (b"EXIF", b"XMP ")
_WEBP_VP8X_EXIF_FLAG = 0x08
_WEBP_VP8X_XMP_FLAG = 0x04


def _orientation_only_exif(exif_data: bytes) -> bytes | None:
    """Build an EXIF payload holding only the Orientation tag, or None if absent.

    Raises ValueError when the EXIF data cannot be parsed or rewritten, so the
    caller rejects the upload instead of storing metadata unchanged.
    """
    try:
        if exif_data.startswith(b"Exif\x00\x00"):
            exif_data = exif_data[6:]
        orientation = piexif.load(b"Exif\x00\x00" + exif_data)["0th"].get(
            piexif.ImageIFD.Orientation
        )
        if orientation is None:
            return None
        clean = piexif.dump({"0th": {piexif.ImageIFD.Orientation: orientation}})
        return clean[6:]
    except Exception:
        raise ValueError("Malformed EXIF data")


def _strip_webp_metadata(file_data: bytes) -> bytes:
    """Remove the EXIF and XMP chunks from a WebP, keeping only the EXIF Orientation.

    Raises ValueError when the RIFF structure cannot be parsed, so the caller
    rejects the upload instead of storing metadata unchanged.
    """
    if file_data[:4] != b"RIFF" or file_data[8:12] != b"WEBP":
        raise ValueError("Not a WebP file")
    riff_end = 8 + int.from_bytes(file_data[4:8], "little")
    if riff_end > len(file_data):
        raise ValueError("Truncated WebP file")

    chunks: list[bytes] = []
    exif_chunk: bytes | None = None
    vp8x_index: int | None = None
    pos = 12
    while pos < riff_end:
        if pos + 8 > riff_end:
            raise ValueError("Malformed WebP chunk")
        fourcc = file_data[pos:pos + 4]
        size = int.from_bytes(file_data[pos + 4:pos + 8], "little")
        end = pos + 8 + size + (size & 1)
        if end > riff_end:
            raise ValueError("Malformed WebP chunk")
        if fourcc == b"EXIF":
            kept = _orientation_only_exif(file_data[pos + 8:pos + 8 + size])
            if kept is not None:
                exif_chunk = b"EXIF" + len(kept).to_bytes(4, "little") + kept + (b"\x00" * (len(kept) & 1))
        elif fourcc not in _WEBP_METADATA_CHUNKS:
            chunk = bytearray(file_data[pos:end])
            if fourcc == b"VP8X" and size >= 1:
                chunk[8] &= ~(_WEBP_VP8X_EXIF_FLAG | _WEBP_VP8X_XMP_FLAG) & 0xFF
                vp8x_index = len(chunks)
            chunks.append(bytes(chunk))
        pos = end

    if exif_chunk is not None:
        if vp8x_index is None:
            # Simple-format WebP has no VP8X, so there is nowhere to flag EXIF
            exif_chunk = None
        else:
            vp8x = bytearray(chunks[vp8x_index])
            vp8x[8] |= _WEBP_VP8X_EXIF_FLAG
            chunks[vp8x_index] = bytes(vp8x)
            chunks.append(exif_chunk)

    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + len(body).to_bytes(4, "little") + body


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
        img.save(buf, comment=b"", **save_kwargs)
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
    """Download the library's watermark logo from object storage and return it as RGBA."""
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
    thumb_save_kwargs: dict = {"format": "JPEG", "quality": 85, "comment": b""}
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
        file_data = _strip_jpeg_metadata(file_data)
    elif content_type == "image/webp":
        file_data = _strip_webp_metadata(file_data)

    ext = EXTENSIONS[content_type]
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
    invalidate_watermark_previews(library.id)
    cache_delete(f"user:storage:{owner.id}")
    return image
