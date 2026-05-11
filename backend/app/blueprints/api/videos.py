"""Video upload blueprint — photographer-authenticated endpoints + internal processing."""

from flask import Blueprint, request, jsonify, g, current_app
from security import require_api_auth, require_api_role
from models import db, Library, Image, Video, VideoProcessingStatus, AuditLogType
from services.audit import write_audit_log
from sqlalchemy import select, func
from datetime import datetime, timezone
from services import storage
from services.redis_client import cache_delete, cache_delete_pattern
from services.videos import validate_video_init, init_video_upload, finalize_video_upload, process_video
from config import VIDEO_UPLOADS_ENABLED, CLOUD_TASKS_SECRET


videos_api = Blueprint("videos_api", __name__, url_prefix="/libraries")


def _feature_gate():
    if not VIDEO_UPLOADS_ENABLED:
        return jsonify({"error": "Video uploads are not enabled"}), 501
    return None


def _get_library(library_id: int, user_id: int) -> Library | None:
    return db.session.execute(
        select(Library).where(
            Library.id == library_id,
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


@videos_api.route("/<int:library_id>/videos/init", methods=["POST"])
@require_api_auth
@require_api_role("photographer")
def init_upload(library_id: int):
    err = _feature_gate()
    if err:
        return err

    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    from models import User
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()
    content_type = (data.get("content_type") or "").strip()
    size = data.get("size")

    if not isinstance(size, int) or size <= 0:
        return jsonify({"error": "size must be a positive integer (bytes)"}), 400

    try:
        validate_video_init(content_type, size, filename)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422

    limits = user.effective_limits

    # Count toward max_images_per_library (TODO: rename to max_media in a later release)
    current_count = (
        db.session.scalar(
            select(func.count()).select_from(Image).where(
                Image.library_id == library_id, Image.deleted_at.is_(None)
            )
        ) or 0
    ) + (
        db.session.scalar(
            select(func.count()).select_from(Video).where(
                Video.library_id == library_id, Video.deleted_at.is_(None)
            )
        ) or 0
    )

    if current_count >= limits["max_images_per_library"]:
        return (
            jsonify({"error": f"Media limit reached ({limits['max_images_per_library']}) for this library."}),
            422,
        )

    image_storage = db.session.scalar(
        select(db.func.coalesce(db.func.sum(Image.size), 0))
        .join(Image.library)
        .where(Library.user_id == user_id, Image.deleted_at.is_(None), Library.deleted_at.is_(None))
    ) or 0
    video_storage = db.session.scalar(
        select(db.func.coalesce(db.func.sum(Video.size), 0))
        .join(Video.library)
        .where(Library.user_id == user_id, Video.deleted_at.is_(None), Library.deleted_at.is_(None))
    ) or 0
    storage_used = image_storage + video_storage

    if storage_used + size > limits["max_storage_bytes"]:
        limit_mb = limits["max_storage_bytes"] // (1024 * 1024)
        return (
            jsonify({"error": f"Storage limit reached ({limit_mb} MB) for your subscription."}),
            422,
        )

    try:
        video, upload_url = init_video_upload(library, user, filename, content_type, size)
    except Exception:
        current_app.logger.exception("Failed to init video upload for library=%s", library_id)
        return jsonify({"error": "Storage error. Please try again."}), 502

    return jsonify({"uuid": video.uuid, "upload_url": upload_url}), 201


@videos_api.route("/<int:library_id>/videos/<video_uuid>/finalize", methods=["POST"])
@require_api_auth
@require_api_role("photographer")
def finalize_upload(library_id: int, video_uuid: str):
    err = _feature_gate()
    if err:
        return err

    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    video = db.session.execute(
        select(Video).where(
            Video.uuid == video_uuid,
            Video.library_id == library_id,
            Video.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if video is None:
        return jsonify({"error": "Video not found"}), 404

    if video.processing_status != VideoProcessingStatus.uploading:
        return jsonify({"error": "Video is not in uploading state"}), 409

    try:
        finalize_video_upload(video)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception:
        current_app.logger.exception("Finalize failed for video=%s", video_uuid)
        return jsonify({"error": "Storage error. Please try again."}), 502

    return jsonify({"uuid": video.uuid, "processing_status": video.processing_status.value})


@videos_api.route("/<int:library_id>/videos/<video_uuid>", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def get_video(library_id: int, video_uuid: str):
    err = _feature_gate()
    if err:
        return err

    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    video = db.session.execute(
        select(Video).where(
            Video.uuid == video_uuid,
            Video.library_id == library_id,
            Video.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if video is None:
        return jsonify({"error": "Video not found"}), 404

    orig_url = thumb_url = None
    if video.processing_status == VideoProcessingStatus.ready:
        orig_url = storage.get_presigned_url(video.storage_path("originals"))
        thumb_url = storage.get_presigned_url(video.storage_path("thumbs"))

    return jsonify(video.to_dict(original_url=orig_url, thumb_url=thumb_url))


@videos_api.route("/<int:library_id>/videos/<int:video_id>", methods=["DELETE"])
@require_api_auth
@require_api_role("photographer")
def delete_video(library_id: int, video_id: int):
    err = _feature_gate()
    if err:
        return err

    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    video = db.session.execute(
        select(Video).where(
            Video.id == video_id,
            Video.library_id == library_id,
            Video.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if video is None:
        return jsonify({"error": "Video not found"}), 404

    video.deleted_at = datetime.now(timezone.utc)
    write_audit_log(
        AuditLogType.video_deleted,
        creator_id=user_id,
        related_object_type="video",
        related_object_id=video.uuid,
    )
    db.session.commit()
    cache_delete_pattern(f"public:library:{library.uuid}:*")
    cache_delete(f"user:storage:{user_id}")
    return "", 204


# ── Internal endpoint — called by Cloud Tasks (or directly in local dev) ──────

internal_bp = Blueprint("internal", __name__, url_prefix="/internal")


@internal_bp.route("/videos/<video_uuid>/process", methods=["POST"])
def process_video_endpoint(video_uuid: str):
    """Cloud Tasks callback to run video thumbnail extraction."""
    secret = request.headers.get("X-Internal-Secret", "")
    if not CLOUD_TASKS_SECRET or secret != CLOUD_TASKS_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        process_video(video_uuid)
    except Exception:
        current_app.logger.exception("Processing failed for video=%s", video_uuid)
        return jsonify({"error": "Processing failed"}), 500

    return jsonify({"ok": True})
