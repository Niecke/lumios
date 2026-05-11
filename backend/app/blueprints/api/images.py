from flask import Blueprint, request, jsonify, g, current_app
from security import require_api_auth, require_api_role
from models import db, User, Library, Image, Video, VideoProcessingStatus, AuditLogType
from services.audit import write_audit_log
from sqlalchemy import select, func, literal, union_all
from datetime import datetime, timezone
from services import storage
from services.redis_client import cache_delete, cache_delete_pattern
from services.images import (
    validate_upload,
    process_and_store_image,
    ALLOWED_CONTENT_TYPES,
    MAX_FILE_SIZE,
    MAGIC_BYTES,
)


images_api = Blueprint("images_api", __name__, url_prefix="/libraries")


def _get_library(library_id: int, user_id: int) -> Library | None:
    return db.session.execute(
        select(Library).where(
            Library.id == library_id,
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()


PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 50


def _media_count(library_id: int) -> int:
    """Total non-deleted images + videos for a library."""
    img = db.session.scalar(
        select(func.count(Image.id)).where(Image.library_id == library_id, Image.deleted_at.is_(None))
    ) or 0
    vid = db.session.scalar(
        select(func.count(Video.id)).where(Video.library_id == library_id, Video.deleted_at.is_(None))
    ) or 0
    return img + vid


def _media_page(library_id: int, offset: int, limit: int) -> list:
    """Return a page of Image/Video objects sorted by created_at desc (union query)."""
    image_q = select(
        Image.id.label("id"),
        literal("photo").label("media_type"),
        Image.created_at.label("created_at"),
    ).where(Image.library_id == library_id, Image.deleted_at.is_(None))

    video_q = select(
        Video.id.label("id"),
        literal("video").label("media_type"),
        Video.created_at.label("created_at"),
    ).where(Video.library_id == library_id, Video.deleted_at.is_(None))

    combined = union_all(image_q, video_q).subquery()
    rows = db.session.execute(
        select(combined.c.id, combined.c.media_type)
        .order_by(combined.c.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    photo_ids = [r.id for r in rows if r.media_type == "photo"]
    video_ids = [r.id for r in rows if r.media_type == "video"]

    images_by_id = {}
    if photo_ids:
        images_by_id = {
            img.id: img
            for img in db.session.execute(select(Image).where(Image.id.in_(photo_ids))).scalars()
        }
    videos_by_id = {}
    if video_ids:
        videos_by_id = {
            v.id: v
            for v in db.session.execute(select(Video).where(Video.id.in_(video_ids))).scalars()
        }

    result = []
    for row in rows:
        if row.media_type == "photo":
            obj = images_by_id.get(row.id)
        else:
            obj = videos_by_id.get(row.id)
        if obj is not None:
            result.append((row.media_type, obj))
    return result


@images_api.route("/<int:library_id>/images", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def list_images(library_id: int):
    user_id = int(g.token_payload["sub"])
    library = _get_library(library_id, user_id)
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(
        PAGE_SIZE_MAX,
        max(1, request.args.get("page_size", PAGE_SIZE_DEFAULT, type=int)),
    )

    user = db.session.get(User, user_id)
    total = _media_count(library_id)
    items = _media_page(library_id, (page - 1) * page_size, page_size)

    media_dicts = []
    for media_type, obj in items:
        if media_type == "photo":
            media_dicts.append(
                obj.to_dict(
                    original_url=storage.get_presigned_url(obj.storage_path("originals")),
                    preview_url=storage.get_presigned_url(obj.storage_path("previews")),
                    thumb_url=storage.get_presigned_url(obj.storage_path("thumbs")),
                )
            )
        else:
            orig_url = thumb_url = None
            if obj.processing_status == VideoProcessingStatus.ready:
                orig_url = storage.get_presigned_url(obj.storage_path("originals"))
                thumb_url = storage.get_presigned_url(obj.storage_path("thumbs"))
            media_dicts.append(obj.to_dict(original_url=orig_url, thumb_url=thumb_url))

    return jsonify(
        {
            "images": media_dicts,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": page * page_size < total,
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

    # TODO: rename max_images_per_library to max_media in a later release
    current_count = (
        db.session.scalar(
            select(db.func.count()).select_from(Image).where(
                Image.library_id == library_id, Image.deleted_at.is_(None)
            )
        ) or 0
    ) + (
        db.session.scalar(
            select(db.func.count()).select_from(Video).where(
                Video.library_id == library_id, Video.deleted_at.is_(None)
            )
        ) or 0
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
            library, user, file_data, file.filename, content_type, is_external=False
        )
    except Exception:
        current_app.logger.exception("GCS upload failed for library=%s", library_id)
        return jsonify({"error": "Storage error. Please try again."}), 502

    original_url = storage.get_presigned_url(image.storage_path("originals"))
    preview_url = storage.get_presigned_url(image.storage_path("previews"))
    thumb_url = storage.get_presigned_url(image.storage_path("thumbs"))
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
    cache_delete_pattern(f"public:library:{library.uuid}:*")
    cache_delete(f"user:storage:{user_id}")
    return "", 204
