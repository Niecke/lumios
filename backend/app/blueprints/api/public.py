from flask import (
    Blueprint,
    jsonify,
    request,
    current_app,
    Response,
    stream_with_context,
)
from main import limiter
from models import (
    db,
    Library,
    Image,
    Video,
    VideoProcessingStatus,
    CustomerState,
    Notification,
    NotificationType,
    User,
    Waitlist,
    AuditLogType,
)
from services.audit import write_audit_log
from sqlalchemy import select, func, or_, literal, union_all
from services import storage
from services.zip_stream import stream_zip
from services.mail import notify_gallery_finished, add_to_brevo_waitlist
from config import MAX_USERS, BREVO_WAITLIST_LIST_ID, VIDEO_UPLOADS_ENABLED
from services.redis_client import get_redis, cache_get, cache_set, cache_delete_pattern
from services.images import validate_upload, process_and_store_image
from services.videos import (
    validate_video_init,
    init_video_upload,
    finalize_video_upload,
)
from datetime import datetime, timezone, date
import re
import json
import hashlib

public_api = Blueprint("public_api", __name__, url_prefix="/public")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _record_library_view(library: Library) -> None:
    """Update last_viewed_at and fire a notification the first time a given
    visitor IP sees this library today. Silently skips if Redis is unavailable."""
    library.last_viewed_at = datetime.now(timezone.utc)

    r = get_redis()
    if r is None:
        return

    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "")
    today = date.today().isoformat()
    visitor_hash = hashlib.sha256(f"{ip}:{today}".encode()).hexdigest()[:16]
    redis_key = f"library:viewed:{library.id}:{visitor_hash}"

    try:
        is_new = r.set(redis_key, 1, nx=True, ex=86400)
    except Exception:
        return  # Redis unavailable — skip notification, last_viewed_at already set

    if is_new:
        notification = Notification(
            type=NotificationType.library_viewed,
            user_id=library.user_id,
            related_object=library.uuid,
        )
        db.session.add(notification)


PUBLIC_PAGE_SIZE_DEFAULT = 20
PUBLIC_PAGE_SIZE_MAX = 50


def _public_media_page(library: Library, page: int, page_size: int) -> tuple[list, int]:
    """Return (media_dicts, total) for the public library view (images + videos merged)."""
    offset = (page - 1) * page_size

    img_count = (
        db.session.scalar(
            select(func.count(Image.id)).where(
                Image.library_id == library.id, Image.deleted_at.is_(None)
            )
        )
        or 0
    )
    vid_count = (
        db.session.scalar(
            select(func.count(Video.id)).where(
                Video.library_id == library.id, Video.deleted_at.is_(None)
            )
        )
        or 0
    )
    total = img_count + vid_count

    image_q = select(
        Image.id.label("id"),
        literal("photo").label("media_type"),
        Image.created_at.label("created_at"),
    ).where(Image.library_id == library.id, Image.deleted_at.is_(None))

    video_q = select(
        Video.id.label("id"),
        literal("video").label("media_type"),
        Video.created_at.label("created_at"),
    ).where(Video.library_id == library.id, Video.deleted_at.is_(None))

    combined = union_all(image_q, video_q).subquery()
    rows = db.session.execute(
        select(combined.c.id, combined.c.media_type)
        .order_by(combined.c.created_at.desc())
        .offset(offset)
        .limit(page_size)
    ).all()

    photo_ids = [r.id for r in rows if r.media_type == "photo"]
    video_ids = [r.id for r in rows if r.media_type == "video"]

    images_by_id = (
        {
            img.id: img
            for img in db.session.execute(
                select(Image).where(Image.id.in_(photo_ids))
            ).scalars()
        }
        if photo_ids
        else {}
    )
    videos_by_id = (
        {
            v.id: v
            for v in db.session.execute(
                select(Video).where(Video.id.in_(video_ids))
            ).scalars()
        }
        if video_ids
        else {}
    )

    preview_variant = "originals" if library.use_original_as_preview else "previews"
    media_dicts = []

    for row in rows:
        if row.media_type == "photo":
            img = images_by_id.get(row.id)
            if not img:
                continue
            media_dicts.append(
                {
                    "uuid": img.uuid,
                    "filename": img.original_filename,
                    "width": img.width,
                    "height": img.height,
                    "media_type": "photo",
                    "customer_state": img.customer_state.value,
                    "preview_url": storage.get_presigned_url(
                        img.storage_path(preview_variant)
                    ),
                    "thumb_url": storage.get_presigned_url(img.storage_path("thumbs")),
                    "download_url": (
                        storage.get_presigned_download_url(
                            img.storage_path(preview_variant), img.original_filename
                        )
                        if library.download_enabled
                        else None
                    ),
                }
            )
        else:
            vid = videos_by_id.get(row.id)
            if not vid:
                continue
            orig_url = thumb_url = None
            if vid.processing_status == VideoProcessingStatus.ready:
                orig_url = storage.get_presigned_url(vid.storage_path("originals"))
                thumb_url = storage.get_presigned_url(vid.storage_path("thumbs"))
            media_dicts.append(
                {
                    "uuid": vid.uuid,
                    "filename": vid.original_filename,
                    "width": vid.width,
                    "height": vid.height,
                    "duration_ms": vid.duration_ms,
                    "media_type": "video",
                    "processing_status": vid.processing_status.value,
                    "hevc_warning": vid.hevc_warning,
                    "customer_state": vid.customer_state.value,
                    "preview_url": orig_url,
                    "thumb_url": thumb_url,
                    "download_url": (
                        storage.get_presigned_download_url(
                            vid.storage_path("originals"), vid.original_filename
                        )
                        if library.download_enabled and orig_url
                        else None
                    ),
                }
            )

    return media_dicts, total


@public_api.route("/libraries/<library_uuid>", methods=["GET"])
@limiter.limit("30 per minute")
def get_public_library(library_uuid: str):
    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404

    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(
        PUBLIC_PAGE_SIZE_MAX,
        max(1, request.args.get("page_size", PUBLIC_PAGE_SIZE_DEFAULT, type=int)),
    )

    if page == 1:
        _record_library_view(library)

    cache_key = f"public:library:{library_uuid}:p{page}:s{page_size}"
    cached = cache_get(cache_key)
    if cached is not None:
        db.session.commit()
        return jsonify(cached)

    media_dicts, total = _public_media_page(library, page, page_size)

    db.session.commit()

    result = {
        "library": {
            "uuid": library.uuid,
            "name": library.name,
            "finished_at": (
                library.finished_at.isoformat() if library.finished_at else None
            ),
            "use_original_as_preview": library.use_original_as_preview,
            "download_enabled": library.download_enabled,
            "public_upload_enabled": library.public_upload_enabled,
            "video_uploads_enabled": VIDEO_UPLOADS_ENABLED,
        },
        "images": media_dicts,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }
    cache_set(cache_key, result, ttl=300)
    return jsonify(result)


@public_api.route(
    "/libraries/<library_uuid>/images/<image_uuid>/state", methods=["PATCH"]
)
@limiter.limit("30 per minute")
def update_customer_state(library_uuid: str, image_uuid: str):
    body = request.get_json(silent=True) or {}
    new_state = body.get("customer_state")
    try:
        state = CustomerState(new_state)
    except (ValueError, KeyError):
        allowed = [s.value for s in CustomerState]
        return jsonify({"error": f"Invalid state. Allowed: {allowed}"}), 400

    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404

    image = db.session.execute(
        select(Image).where(
            Image.uuid == image_uuid,
            Image.library_id == library.id,
            Image.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if image is None:
        return jsonify({"error": "Image not found"}), 404

    image.customer_state = state
    db.session.commit()
    cache_delete_pattern(f"public:library:{library_uuid}:*")
    return jsonify({"uuid": image.uuid, "customer_state": state.value})


@public_api.route(
    "/libraries/<library_uuid>/videos/<video_uuid>/state", methods=["PATCH"]
)
@limiter.limit("30 per minute")
def update_video_customer_state(library_uuid: str, video_uuid: str):
    body = request.get_json(silent=True) or {}
    new_state = body.get("customer_state")
    try:
        state = CustomerState(new_state)
    except (ValueError, KeyError):
        allowed = [s.value for s in CustomerState]
        return jsonify({"error": f"Invalid state. Allowed: {allowed}"}), 400

    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404

    video = db.session.execute(
        select(Video).where(
            Video.uuid == video_uuid,
            Video.library_id == library.id,
            Video.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if video is None:
        return jsonify({"error": "Video not found"}), 404

    video.customer_state = state
    db.session.commit()
    cache_delete_pattern(f"public:library:{library_uuid}:*")
    return jsonify({"uuid": video.uuid, "customer_state": state.value})


@public_api.route("/libraries/<library_uuid>/finish", methods=["POST"])
@limiter.limit("5 per minute")
def finish_library(library_uuid: str):
    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404

    if library.finished_at is not None:
        return jsonify({"error": "Library is already marked as finished"}), 409

    liked_images = (
        db.session.scalar(
            select(db.func.count())
            .select_from(Image)
            .where(
                Image.library_id == library.id,
                Image.deleted_at.is_(None),
                Image.customer_state == CustomerState.liked,
            )
        )
        or 0
    )
    liked_videos = (
        db.session.scalar(
            select(db.func.count())
            .select_from(Video)
            .where(
                Video.library_id == library.id,
                Video.deleted_at.is_(None),
                Video.customer_state == CustomerState.liked,
            )
        )
        or 0
    )
    liked_count = liked_images + liked_videos

    if liked_count == 0:
        return (
            jsonify({"error": "You must like at least one photo before finishing"}),
            422,
        )

    library.finished_at = datetime.now(timezone.utc)

    notification = Notification(
        type=NotificationType.library_marked,
        user_id=library.user_id,
        related_object=library.uuid,
    )
    db.session.add(notification)
    write_audit_log(
        AuditLogType.library_finished,
        related_object_type="library",
        related_object_id=library.uuid,
    )
    db.session.commit()
    cache_delete_pattern(f"public:library:{library_uuid}:*")

    notify_gallery_finished(
        photographer_email=library.photographer.email,
        library_name=library.name,
        library_uuid=library.uuid,
        liked_count=liked_count,
    )

    return jsonify(
        {
            "uuid": library.uuid,
            "finished_at": library.finished_at.isoformat(),
        }
    )


@public_api.route(
    "/libraries/<library_uuid>/images/<image_uuid>/download", methods=["GET"]
)
@limiter.limit("30 per minute")
def download_image(library_uuid: str, image_uuid: str):
    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404

    if not library.download_enabled:
        return jsonify({"error": "Downloads are not enabled for this library"}), 403

    image = db.session.execute(
        select(Image).where(
            Image.uuid == image_uuid,
            Image.library_id == library.id,
            Image.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if image is None:
        return jsonify({"error": "Image not found"}), 404

    variant = "originals" if library.use_original_as_preview else "previews"
    download_url = storage.get_presigned_download_url(
        image.storage_path(variant), image.original_filename
    )

    write_audit_log(
        AuditLogType.picture_downloaded,
        related_object_type="image",
        related_object_id=image.uuid,
    )
    db.session.commit()

    return jsonify({"download_url": download_url})


@public_api.route(
    "/libraries/<library_uuid>/videos/<video_uuid>/download", methods=["GET"]
)
@limiter.limit("30 per minute")
def download_video(library_uuid: str, video_uuid: str):
    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404

    if not library.download_enabled:
        return jsonify({"error": "Downloads are not enabled for this library"}), 403

    video = db.session.execute(
        select(Video).where(
            Video.uuid == video_uuid,
            Video.library_id == library.id,
            Video.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if video is None:
        return jsonify({"error": "Video not found"}), 404

    download_url = storage.get_presigned_download_url(
        video.storage_path("originals"), video.original_filename
    )

    write_audit_log(
        AuditLogType.video_downloaded,
        related_object_type="video",
        related_object_id=video.uuid,
    )
    db.session.commit()

    return jsonify({"download_url": download_url})


@public_api.route("/libraries/<library_uuid>/download", methods=["GET"])
@limiter.limit("3 per minute")
def download_library_zip(library_uuid: str):
    """Stream a ZIP of all images and videos in the library."""
    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404
    if not library.download_enabled:
        return jsonify({"error": "Downloads are not enabled for this library"}), 403

    images = (
        db.session.execute(
            select(Image)
            .where(Image.library_id == library.id, Image.deleted_at.is_(None))
            .order_by(Image.created_at.asc())
        )
        .scalars()
        .all()
    )
    videos = (
        db.session.execute(
            select(Video)
            .where(
                Video.library_id == library.id,
                Video.deleted_at.is_(None),
                Video.processing_status == VideoProcessingStatus.ready,
            )
            .order_by(Video.created_at.asc())
        )
        .scalars()
        .all()
    )

    if not images and not videos:
        return jsonify({"error": "Library has no media"}), 404

    variant = "originals" if library.use_original_as_preview else "previews"
    snapshots = []
    for img in images:
        snapshots.append((img.original_filename, img.storage_path(variant)))
        write_audit_log(
            AuditLogType.picture_downloaded,
            related_object_type="image",
            related_object_id=img.uuid,
        )
    for vid in videos:
        snapshots.append((vid.original_filename, vid.storage_path("originals")))
        write_audit_log(
            AuditLogType.video_downloaded,
            related_object_type="video",
            related_object_id=vid.uuid,
        )
    db.session.commit()

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", library.name).strip("_") or "library"
    zip_filename = f"{safe_name}.zip"

    def entries():
        for filename, key in snapshots:
            yield filename, lambda k=key: storage.iter_object_chunks(k)

    response = Response(
        stream_with_context(stream_zip(entries())),
        mimetype="application/zip",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{zip_filename}"'
    response.headers["Cache-Control"] = "no-store"
    return response


@public_api.route("/libraries/<library_uuid>/images", methods=["POST"])
@limiter.limit("10 per minute")
def public_upload_image(library_uuid: str):
    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404
    if not library.public_upload_enabled:
        return (
            jsonify({"error": "Public uploads are not enabled for this library"}),
            403,
        )

    owner = db.session.get(User, library.user_id)
    if owner is None:
        return jsonify({"error": "Library owner not found"}), 404

    limits = owner.effective_limits

    # TODO: rename max_images_per_library to max_media in a later release
    current_count = (
        db.session.scalar(
            select(db.func.count())
            .select_from(Image)
            .where(Image.library_id == library.id, Image.deleted_at.is_(None))
        )
        or 0
    ) + (
        db.session.scalar(
            select(db.func.count())
            .select_from(Video)
            .where(Video.library_id == library.id, Video.deleted_at.is_(None))
        )
        or 0
    )

    if current_count >= limits["max_images_per_library"]:
        return (
            jsonify(
                {
                    "error": f"Media limit reached ({limits['max_images_per_library']}) for this library."
                }
            ),
            422,
        )

    image_storage = (
        db.session.scalar(
            select(db.func.coalesce(db.func.sum(Image.size), 0))
            .join(Image.library)
            .where(
                Library.user_id == owner.id,
                Image.deleted_at.is_(None),
                Library.deleted_at.is_(None),
            )
        )
        or 0
    )
    video_storage = (
        db.session.scalar(
            select(db.func.coalesce(db.func.sum(Video.size), 0))
            .join(Video.library)
            .where(
                Library.user_id == owner.id,
                Video.deleted_at.is_(None),
                Library.deleted_at.is_(None),
            )
        )
        or 0
    )
    storage_used = image_storage + video_storage

    if storage_used >= limits["max_storage_bytes"]:
        limit_mb = limits["max_storage_bytes"] // (1024 * 1024)
        return (
            jsonify(
                {"error": f"Storage limit reached ({limit_mb} MB) for this library."}
            ),
            422,
        )

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    content_type = file.content_type or ""
    file_data = file.read()

    try:
        validate_upload(file_data, content_type, file.filename)
    except ValueError as exc:
        msg = str(exc)
        if "Only JPEG" in msg:
            return jsonify({"error": msg}), 415
        if "too large" in msg:
            return jsonify({"error": msg}), 413
        return jsonify({"error": msg}), 415

    try:
        image = process_and_store_image(
            library, owner, file_data, file.filename, content_type, is_external=True
        )
    except Exception:
        current_app.logger.exception(
            "GCS upload failed for public upload library=%s", library_uuid
        )
        return jsonify({"error": "Storage error. Please try again."}), 502

    return jsonify({"uuid": image.uuid}), 201


# ── Public video upload (Architecture B — presigned PUT) ──────────────────────


@public_api.route("/libraries/<library_uuid>/videos/init", methods=["POST"])
@limiter.limit("10 per minute")
def public_init_video_upload(library_uuid: str):
    if not VIDEO_UPLOADS_ENABLED:
        return jsonify({"error": "Video uploads are not enabled"}), 501

    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404
    if not library.public_upload_enabled:
        return (
            jsonify({"error": "Public uploads are not enabled for this library"}),
            403,
        )

    owner = db.session.get(User, library.user_id)
    if owner is None:
        return jsonify({"error": "Library owner not found"}), 404

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

    limits = owner.effective_limits

    current_count = (
        db.session.scalar(
            select(db.func.count())
            .select_from(Image)
            .where(Image.library_id == library.id, Image.deleted_at.is_(None))
        )
        or 0
    ) + (
        db.session.scalar(
            select(db.func.count())
            .select_from(Video)
            .where(Video.library_id == library.id, Video.deleted_at.is_(None))
        )
        or 0
    )

    if current_count >= limits["max_images_per_library"]:
        return (
            jsonify(
                {
                    "error": f"Media limit reached ({limits['max_images_per_library']}) for this library."
                }
            ),
            422,
        )

    image_storage = (
        db.session.scalar(
            select(db.func.coalesce(db.func.sum(Image.size), 0))
            .join(Image.library)
            .where(
                Library.user_id == owner.id,
                Image.deleted_at.is_(None),
                Library.deleted_at.is_(None),
            )
        )
        or 0
    )
    video_storage = (
        db.session.scalar(
            select(db.func.coalesce(db.func.sum(Video.size), 0))
            .join(Video.library)
            .where(
                Library.user_id == owner.id,
                Video.deleted_at.is_(None),
                Library.deleted_at.is_(None),
            )
        )
        or 0
    )
    storage_used = image_storage + video_storage

    if storage_used + size > limits["max_storage_bytes"]:
        limit_mb = limits["max_storage_bytes"] // (1024 * 1024)
        return (
            jsonify(
                {"error": f"Storage limit reached ({limit_mb} MB) for this library."}
            ),
            422,
        )

    try:
        video, upload_url = init_video_upload(
            library, owner, filename, content_type, size, is_external=True
        )
    except Exception:
        current_app.logger.exception(
            "Public video init failed for library=%s", library_uuid
        )
        return jsonify({"error": "Storage error. Please try again."}), 502

    return jsonify({"uuid": video.uuid, "upload_url": upload_url}), 201


@public_api.route(
    "/libraries/<library_uuid>/videos/<video_uuid>/finalize", methods=["POST"]
)
@limiter.limit("10 per minute")
def public_finalize_video_upload(library_uuid: str, video_uuid: str):
    if not VIDEO_UPLOADS_ENABLED:
        return jsonify({"error": "Video uploads are not enabled"}), 501

    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404
    if not library.public_upload_enabled:
        return (
            jsonify({"error": "Public uploads are not enabled for this library"}),
            403,
        )

    video = db.session.execute(
        select(Video).where(
            Video.uuid == video_uuid,
            Video.library_id == library.id,
            Video.deleted_at.is_(None),
            Video.is_external.is_(True),
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
        current_app.logger.exception(
            "Public video finalize failed for video=%s", video_uuid
        )
        return jsonify({"error": "Storage error. Please try again."}), 502

    return jsonify(
        {"uuid": video.uuid, "processing_status": video.processing_status.value}
    )


@public_api.route("/libraries/<library_uuid>/videos/<video_uuid>", methods=["GET"])
@limiter.limit("60 per minute")
def public_get_video_status(library_uuid: str, video_uuid: str):
    """Poll video processing status (used after finalize)."""
    if not VIDEO_UPLOADS_ENABLED:
        return jsonify({"error": "Video uploads are not enabled"}), 501

    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    if library.is_private:
        return jsonify({"error": "Library not found"}), 404

    video = db.session.execute(
        select(Video).where(
            Video.uuid == video_uuid,
            Video.library_id == library.id,
            Video.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if video is None:
        return jsonify({"error": "Video not found"}), 404

    return jsonify(
        {
            "uuid": video.uuid,
            "processing_status": video.processing_status.value,
            "hevc_warning": video.hevc_warning,
        }
    )


@public_api.route("/registration_status", methods=["GET"])
@limiter.limit("30 per minute")
def registration_status():
    """Return whether new registrations are currently open."""
    cached = cache_get("registration:status")
    if cached is not None:
        return jsonify(cached)

    slot_count = (
        db.session.execute(
            select(func.count(User.id)).where(
                or_(User.active.is_(True), User.activation_pending.is_(True)),
                User.deleted_at.is_(None),
            )
        ).scalar()
        or 0
    )
    result = {"can_register": slot_count < MAX_USERS}
    cache_set("registration:status", result, ttl=120)
    return jsonify(result)


@public_api.route("/waitlist", methods=["POST"])
@limiter.limit("3 per minute")
def join_waitlist():
    """Add an email address to the waitlist (Brevo contact list)."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    if not email:
        return jsonify({"error": "Email is required"}), 400
    if not _EMAIL_RE.match(email):
        return jsonify({"error": "Invalid email address"}), 400

    existing = db.session.execute(
        select(Waitlist).where(Waitlist.email == email)
    ).scalar_one_or_none()
    if not existing:
        db.session.add(Waitlist(email=email))
        db.session.commit()

    add_to_brevo_waitlist(email, BREVO_WAITLIST_LIST_ID)
    current_app.logger.info("Waitlist signup: %s", email, extra={"log_type": "audit"})
    return jsonify({"ok": True})


@public_api.route("/client-errors", methods=["POST"])
@limiter.limit("5 per minute")
def report_client_error():
    data = request.get_json(silent=True) or {}

    message = str(data.get("message") or "Unknown error")[:2000]
    stack = str(data.get("stack") or "")[:5000]
    url = str(data.get("url") or "")[:500]
    line_number = int(data.get("line_number") or 0)
    col_number = int(data.get("col_number") or 0)
    user_agent = request.headers.get("User-Agent", "")[:500]

    print(
        json.dumps(
            {
                "severity": "ERROR",
                "@type": "type.googleapis.com/google.devtools.clouderrorreporting.v1beta1.ReportedErrorEvent",
                "message": f"{message}\n{stack}".strip(),
                "serviceContext": {"service": "lumios-frontend"},
                "context": {
                    "httpRequest": {
                        "url": url,
                        "userAgent": user_agent,
                    },
                    "reportLocation": {
                        "filePath": url,
                        "lineNumber": line_number,
                        "columnNumber": col_number,
                    },
                },
            }
        ),
        flush=True,
    )
    return "", 204
