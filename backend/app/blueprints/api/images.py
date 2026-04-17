from flask import Blueprint, request, jsonify, g, current_app
from security import require_api_auth, require_api_role
from models import db, User, Library, Image, AuditLogType
from services.audit import write_audit_log
from sqlalchemy import select, func
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
    total = (
        db.session.scalar(
            select(func.count(Image.id)).where(
                Image.library_id == library_id, Image.deleted_at.is_(None)
            )
        )
        or 0
    )

    images = (
        db.session.execute(
            select(Image)
            .where(Image.library_id == library_id, Image.deleted_at.is_(None))
            .order_by(Image.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
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
