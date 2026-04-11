from flask import Blueprint, request, jsonify, g, current_app, Response
from security import require_api_auth, require_api_role
from models import db, User, Library, Image, AuditLogType
from services.audit import write_audit_log
from sqlalchemy import select, func
from datetime import datetime, timezone
import io
from PIL import Image as PilImage
from services import storage
from services.redis_client import cache_delete_pattern
from blueprints.api.images import (
    _build_placeholder_image,
    _create_watermarked_preview,
    _load_library_logo,
    WATERMARK_LOGO_MAX_BYTES,
    WATERMARK_LOGO_MAGIC,
)

libraries_api = Blueprint("libraries_api", __name__, url_prefix="/libraries")

MAX_NAME_LENGTH = 255


PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


@libraries_api.route("", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def list_libraries():
    user_id = int(g.token_payload["sub"])

    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(
        PAGE_SIZE_MAX, max(1, request.args.get("page_size", PAGE_SIZE_DEFAULT, type=int))
    )

    total = db.session.scalar(
        select(func.count(Library.id)).where(
            Library.user_id == user_id, Library.deleted_at.is_(None)
        )
    ) or 0

    libraries = (
        db.session.execute(
            select(Library)
            .where(Library.user_id == user_id, Library.deleted_at.is_(None))
            .order_by(Library.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    user = db.session.get(User, user_id)
    return jsonify(
        {
            "libraries": [lib.to_dict() for lib in libraries],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": page * page_size < total,
            "max_libraries": user.effective_limits["max_libraries"] if user else None,
        }
    )


@libraries_api.route("", methods=["POST"])
@require_api_auth
@require_api_role("photographer")
def create_library():
    user_id = int(g.token_payload["sub"])
    user = db.session.get(User, user_id)
    if user is None:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if len(name) > MAX_NAME_LENGTH:
        return (
            jsonify({"error": f"name must be {MAX_NAME_LENGTH} characters or fewer"}),
            400,
        )

    current_count = db.session.execute(
        select(db.func.count())
        .select_from(Library)
        .where(
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar()

    limits = user.effective_limits
    if current_count >= limits["max_libraries"]:
        return (
            jsonify(
                {
                    "error": f"Library limit reached ({limits['max_libraries']}). Delete an existing library to create a new one."
                }
            ),
            422,
        )

    library = Library(user_id=user_id, name=name)
    db.session.add(library)
    db.session.flush()
    write_audit_log(
        AuditLogType.library_created,
        creator_id=user_id,
        related_object_type="library",
        related_object_id=library.uuid,
    )
    db.session.commit()
    return jsonify(library.to_dict()), 201


@libraries_api.route("/uuid/<library_uuid>", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def get_library_by_uuid(library_uuid: str):
    user_id = int(g.token_payload["sub"])
    library = db.session.execute(
        select(Library).where(
            Library.uuid == library_uuid,
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404
    return jsonify(library.to_dict())


@libraries_api.route("/<int:library_id>", methods=["PATCH"])
@require_api_auth
@require_api_role("photographer")
def update_library(library_id: int):
    user_id = int(g.token_payload["sub"])
    library = db.session.execute(
        select(Library).where(
            Library.id == library_id,
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name must not be empty"}), 400
        if len(name) > MAX_NAME_LENGTH:
            return (
                jsonify(
                    {"error": f"name must be {MAX_NAME_LENGTH} characters or fewer"}
                ),
                400,
            )
        library.name = name

    if "use_original_as_preview" in data:
        value = data["use_original_as_preview"]
        if not isinstance(value, bool):
            return jsonify({"error": "use_original_as_preview must be a boolean"}), 400
        library.use_original_as_preview = value

    if "download_enabled" in data:
        value = data["download_enabled"]
        if not isinstance(value, bool):
            return jsonify({"error": "download_enabled must be a boolean"}), 400
        library.download_enabled = value

    if "is_private" in data:
        value = data["is_private"]
        if not isinstance(value, bool):
            return jsonify({"error": "is_private must be a boolean"}), 400
        library.is_private = value

    if "watermark_scale" in data:
        scale = data["watermark_scale"]
        if not isinstance(scale, (int, float)) or not (0.05 <= float(scale) <= 0.50):
            return (
                jsonify({"error": "watermark_scale must be between 0.05 and 0.50"}),
                400,
            )
        library.watermark_scale = float(scale)

    if "watermark_position" in data:
        if data["watermark_position"] not in VALID_WATERMARK_POSITIONS:
            return jsonify({"error": "invalid watermark_position"}), 400
        library.watermark_position = data["watermark_position"]

    write_audit_log(
        AuditLogType.library_edited,
        creator_id=user_id,
        related_object_type="library",
        related_object_id=library.uuid,
    )
    db.session.commit()
    cache_delete_pattern(f"public:library:{library.uuid}:*")
    return jsonify(library.to_dict())


VALID_WATERMARK_POSITIONS = {
    "bottom_right",
    "bottom_left",
    "top_right",
    "top_left",
    "center",
}


@libraries_api.route("/<int:library_id>/watermark", methods=["POST"])
@require_api_auth
@require_api_role("photographer")
def upload_watermark(library_id: int):
    user_id = int(g.token_payload["sub"])
    library = db.session.execute(
        select(Library).where(
            Library.id == library_id,
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    content_type = file.content_type or ""
    if content_type != "image/png":
        return jsonify({"error": "Watermark must be a PNG image"}), 415

    file_data = file.read()
    if len(file_data) > WATERMARK_LOGO_MAX_BYTES:
        return jsonify({"error": "Watermark file too large (max 5 MB)"}), 413
    if not file_data.startswith(WATERMARK_LOGO_MAGIC):
        return jsonify({"error": "File content does not match its declared type"}), 415

    try:
        logo = PilImage.open(io.BytesIO(file_data))
        logo.verify()
    except Exception:
        return jsonify({"error": "File is not a valid PNG image"}), 415

    gcs_key = f"watermarks/{user_id}/{library_id}/watermark.png"
    try:
        storage.ensure_bucket()
        storage.upload_fileobj(io.BytesIO(file_data), gcs_key, "image/png")
    except Exception:
        current_app.logger.exception("GCS upload failed for watermark key=%s", gcs_key)
        return jsonify({"error": "Storage error. Please try again."}), 502

    library.watermark_gcs_key = gcs_key
    if library.watermark_scale is None:
        library.watermark_scale = 0.2
    if library.watermark_position is None:
        library.watermark_position = "bottom_right"
    db.session.commit()
    return jsonify(library.to_dict()), 200


@libraries_api.route("/<int:library_id>/watermark", methods=["DELETE"])
@require_api_auth
@require_api_role("photographer")
def delete_watermark(library_id: int):
    user_id = int(g.token_payload["sub"])
    library = db.session.execute(
        select(Library).where(
            Library.id == library_id,
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    if library.watermark_gcs_key:
        try:
            storage.delete_object(library.watermark_gcs_key)
        except Exception:
            current_app.logger.warning(
                "Failed to delete watermark from GCS key=%s", library.watermark_gcs_key
            )
        library.watermark_gcs_key = None
        db.session.commit()
    return jsonify(library.to_dict()), 200


@libraries_api.route("/<int:library_id>/watermark/preview", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def watermark_preview(library_id: int):
    user_id = int(g.token_payload["sub"])
    library = db.session.execute(
        select(Library).where(
            Library.id == library_id,
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    if not library.watermark_gcs_key:
        return jsonify({"error": "No watermark logo configured for this library"}), 400

    try:
        scale = float(request.args.get("scale", library.watermark_scale or 0.2))
        scale = max(0.05, min(0.50, scale))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid scale parameter"}), 400

    position = request.args.get(
        "position", library.watermark_position or "bottom_right"
    )
    if position not in VALID_WATERMARK_POSITIONS:
        return jsonify({"error": "Invalid position parameter"}), 400

    sample_image = (
        db.session.execute(
            select(Image)
            .where(Image.library_id == library_id, Image.deleted_at.is_(None))
            .order_by(Image.created_at.desc())
        )
        .scalars()
        .first()
    )

    if sample_image is not None:
        try:
            original_data = storage.get_object_bytes(sample_image.storage_path("originals"))
        except Exception:
            current_app.logger.exception(
                "Failed to fetch sample image for watermark preview, library=%s", library_id
            )
            return jsonify({"error": "Could not load sample photo"}), 502

        try:
            pil_img = PilImage.open(io.BytesIO(original_data))
        except Exception:
            return jsonify({"error": "Could not open sample photo"}), 502

        original_file_size = len(original_data)
    else:
        pil_img = _build_placeholder_image()
        original_file_size = 0

    logo = _load_library_logo(library)
    if logo is None:
        return jsonify({"error": "Could not load watermark logo"}), 502

    preview_buf = _create_watermarked_preview(
        pil_img,
        original_file_size=original_file_size,
        logo=logo,
        logo_scale=scale,
        logo_position=position,
    )
    logo.close()
    pil_img.close()

    return Response(preview_buf.read(), mimetype="image/jpeg")


@libraries_api.route("/<int:library_id>", methods=["DELETE"])
@require_api_auth
@require_api_role("photographer")
def delete_library(library_id: int):
    user_id = int(g.token_payload["sub"])
    library = db.session.execute(
        select(Library).where(
            Library.id == library_id,
            Library.user_id == user_id,
            Library.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if library is None:
        return jsonify({"error": "Library not found"}), 404

    library.deleted_at = datetime.now(timezone.utc)
    write_audit_log(
        AuditLogType.library_deleted,
        creator_id=user_id,
        related_object_type="library",
        related_object_id=library.uuid,
    )
    db.session.commit()
    cache_delete_pattern(f"public:library:{library.uuid}:*")
    return "", 204
