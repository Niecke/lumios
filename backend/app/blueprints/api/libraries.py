from flask import Blueprint, request, jsonify, g
from security import require_api_auth, require_api_role
from models import db, User, Library, AuditLogType
from services.audit import write_audit_log
from sqlalchemy import select
from datetime import datetime, timezone

libraries_api = Blueprint("libraries_api", __name__, url_prefix="/libraries")

MAX_NAME_LENGTH = 255


@libraries_api.route("", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def list_libraries():
    user_id = int(g.token_payload["sub"])
    libraries = (
        db.session.execute(
            select(Library)
            .where(Library.user_id == user_id, Library.deleted_at.is_(None))
            .order_by(Library.created_at.desc())
        )
        .scalars()
        .all()
    )
    user = db.session.get(User, user_id)
    return jsonify(
        {
            "libraries": [lib.to_dict() for lib in libraries],
            "count": len(libraries),
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

    write_audit_log(
        AuditLogType.library_edited,
        creator_id=user_id,
        related_object_type="library",
        related_object_id=library.uuid,
    )
    db.session.commit()
    return jsonify(library.to_dict())


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
    return "", 204
