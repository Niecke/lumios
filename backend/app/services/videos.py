"""Video upload service — init presigned upload, finalize, async processing."""

from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
import uuid as uuid_module
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from flask import current_app
from PIL import Image as PilImage

from config import (
    ALLOWED_VIDEO_TYPES,
    MAX_VIDEO_FILE_SIZE,
    VIDEO_EXTENSIONS,
    CLOUD_TASKS_QUEUE,
)
from models import db, Video, VideoProcessingStatus, AuditLogType
from services.audit import write_audit_log
from services import storage
from services.images import _load_library_logo, _create_watermarked_preview
from services.redis_client import cache_delete, cache_delete_pattern

if TYPE_CHECKING:
    from models import Library, User

THUMB_SIZE = 600


def validate_video_init(content_type: str, size: int, filename: str) -> None:
    """Raise ValueError with a user-facing message on any rejection."""
    if content_type not in ALLOWED_VIDEO_TYPES:
        raise ValueError("Only MP4, MOV, WebM, and M4V videos are allowed")
    if size > MAX_VIDEO_FILE_SIZE:
        limit_mb = MAX_VIDEO_FILE_SIZE // (1024 * 1024)
        raise ValueError(f"File too large (max {limit_mb} MB)")
    if not filename:
        raise ValueError("Filename is required")


def init_video_upload(
    library: "Library",
    owner: "User",
    filename: str,
    content_type: str,
    size: int,
    is_external: bool = False,
) -> tuple["Video", str]:
    """Create a Video DB row (status=uploading) and return a presigned PUT URL."""
    ext = VIDEO_EXTENSIONS.get(content_type, "mp4")
    video_uuid = str(uuid_module.uuid4())
    s3_key = f"{video_uuid}.{ext}"
    original_path = f"photos/{owner.id}/{library.id}/originals/{s3_key}"

    storage.ensure_bucket()
    upload_url = storage.create_presigned_put_url(original_path, content_type, expires_in=3600)

    video = Video(
        uuid=video_uuid,
        library_id=library.id,
        s3_key=s3_key,
        original_filename=filename,
        content_type=content_type,
        size=size,
        processing_status=VideoProcessingStatus.uploading,
        is_external=is_external,
    )
    db.session.add(video)
    db.session.flush()

    write_audit_log(
        AuditLogType.video_uploaded,
        creator_id=None if is_external else owner.id,
        related_object_type="video",
        related_object_id=video.uuid,
    )
    db.session.commit()
    return video, upload_url


def finalize_video_upload(video: "Video") -> None:
    """Verify the object exists in storage then enqueue processing."""
    original_path = video.storage_path("originals")
    if not storage.object_exists(original_path):
        raise ValueError("Video not found in storage — upload may have failed")

    video.processing_status = VideoProcessingStatus.processing
    db.session.commit()

    if CLOUD_TASKS_QUEUE:
        from services.cloud_tasks import enqueue_video_processing
        enqueue_video_processing(video.uuid)
    else:
        import threading
        app = current_app._get_current_object()
        thread = threading.Thread(
            target=_process_video_in_thread,
            args=(app, video.uuid),
            daemon=True,
        )
        thread.start()


def _process_video_in_thread(app, video_uuid: str) -> None:
    with app.app_context():
        try:
            process_video(video_uuid)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "Background video processing failed for %s", video_uuid
            )


def process_video(video_uuid: str) -> None:
    """Download video from storage, extract watermarked thumbnail, update DB row."""
    from sqlalchemy import select

    video = db.session.execute(
        select(Video).where(Video.uuid == video_uuid)
    ).scalar_one_or_none()
    if video is None:
        raise ValueError(f"Video {video_uuid} not found")

    original_path = video.storage_path("originals")
    thumb_path = video.storage_path("thumbs")

    ext = video.s3_key.rsplit(".", 1)[-1]
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=f".{ext}")
    try:
        # Download full video to temp file
        with os.fdopen(tmp_fd, "wb") as tmp:
            for chunk in storage.iter_object_chunks(original_path):
                tmp.write(chunk)

        # Extract frame and probe metadata
        info = _extract_video_info(tmp_path)
    except Exception:
        current_app.logger.exception("Video extraction failed for %s", video_uuid)
        video.processing_status = VideoProcessingStatus.failed
        db.session.commit()
        return
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    try:
        pil_frame: PilImage.Image = info["frame"]
        logo = _load_library_logo(video.library)
        preview_buf = _create_watermarked_preview(
            pil_frame,
            original_file_size=pil_frame.size[0] * pil_frame.size[1] * 3,
            logo=logo,
            logo_scale=video.library.watermark_scale or 0.2,
            logo_position=video.library.watermark_position or "bottom_right",
        )
        if logo is not None:
            logo.close()

        # Resize to THUMB_SIZE for thumbnail
        thumb_img = pil_frame.copy()
        thumb_img.thumbnail((THUMB_SIZE, THUMB_SIZE))
        if thumb_img.mode != "RGB":
            thumb_img = thumb_img.convert("RGB")
        thumb_buf = io.BytesIO()
        thumb_img.save(thumb_buf, format="JPEG", quality=85)
        thumb_buf.seek(0)
        thumb_img.close()
        pil_frame.close()

        storage.upload_fileobj(thumb_buf, thumb_path, "image/jpeg")
    except Exception:
        current_app.logger.exception("Thumbnail upload failed for %s", video_uuid)
        video.processing_status = VideoProcessingStatus.failed
        db.session.commit()
        return

    video.width = info.get("width")
    video.height = info.get("height")
    video.duration_ms = info.get("duration_ms")
    video.video_codec = info.get("video_codec")
    video.audio_codec = info.get("audio_codec")
    video.bitrate = info.get("bitrate")
    video.hevc_warning = bool(info.get("hevc_warning"))
    video.processing_status = VideoProcessingStatus.ready
    db.session.commit()

    cache_delete_pattern(f"public:library:{video.library.uuid}:*")
    cache_delete(f"user:storage:{video.library.user_id}")


def _extract_video_info(tmp_path: str) -> dict:
    """Extract one frame and metadata from a video file using imageio-ffmpeg."""
    import imageio_ffmpeg

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    # Parse metadata from ffmpeg -i stderr
    info_proc = subprocess.run(
        [ffmpeg_exe, "-i", tmp_path, "-hide_banner"],
        capture_output=True,
        text=True,
    )
    stderr = info_proc.stderr

    video_match = re.search(r"Video:\s+(\w+)", stderr)
    video_codec = video_match.group(1).lower() if video_match else None
    hevc_warning = video_codec in ("hevc", "h265")

    audio_match = re.search(r"Audio:\s+(\w+)", stderr)
    audio_codec = audio_match.group(1).lower() if audio_match else None

    bitrate_match = re.search(r"bitrate:\s+(\d+)\s+kb/s", stderr)
    bitrate = int(bitrate_match.group(1)) * 1000 if bitrate_match else None

    duration_match = re.search(r"Duration:\s+(\d+):(\d+):(\d+)\.(\d+)", stderr)
    duration_ms = None
    if duration_match:
        h, m, s, cs = (int(x) for x in duration_match.groups())
        duration_ms = ((h * 3600 + m * 60 + s) * 1000) + cs * 10

    # Extract frame at 1s, fall back to 0s for short clips
    frame_jpeg = _extract_frame_jpeg(ffmpeg_exe, tmp_path, seek_seconds=1)
    if not frame_jpeg:
        frame_jpeg = _extract_frame_jpeg(ffmpeg_exe, tmp_path, seek_seconds=0)
    if not frame_jpeg:
        raise ValueError("Could not extract video frame")

    pil_frame = PilImage.open(io.BytesIO(frame_jpeg)).convert("RGB")
    width, height = pil_frame.size

    return {
        "frame": pil_frame,
        "width": width,
        "height": height,
        "duration_ms": duration_ms,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "bitrate": bitrate,
        "hevc_warning": hevc_warning,
    }


def _extract_frame_jpeg(ffmpeg_exe: str, tmp_path: str, seek_seconds: int) -> bytes:
    proc = subprocess.run(
        [
            ffmpeg_exe,
            "-ss", str(seek_seconds),
            "-i", tmp_path,
            "-vframes", "1",
            "-f", "image2",
            "-vcodec", "mjpeg",
            "pipe:1",
            "-hide_banner",
            "-loglevel", "error",
        ],
        capture_output=True,
    )
    return proc.stdout if proc.stdout else b""
