from flask import Blueprint, jsonify, request
from main import limiter
from models import db, Library, Image, CustomerState, Notification, NotificationType
from sqlalchemy import select
from services import storage
from datetime import datetime, timezone

public_api = Blueprint("public_api", __name__, url_prefix="/public")


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

    images = (
        db.session.execute(
            select(Image)
            .where(Image.library_id == library.id, Image.deleted_at.is_(None))
            .order_by(Image.created_at.desc())
        )
        .scalars()
        .all()
    )

    image_dicts = [
        {
            "uuid": img.uuid,
            "filename": img.original_filename,
            "width": img.width,
            "height": img.height,
            "customer_state": img.customer_state.value,
            "preview_url": storage.get_presigned_url(img.storage_path("previews")),
            "thumb_url": storage.get_presigned_url(img.storage_path("thumbs")),
        }
        for img in images
    ]

    return jsonify(
        {
            "library": {
                "uuid": library.uuid,
                "name": library.name,
                "finished_at": (
                    library.finished_at.isoformat() if library.finished_at else None
                ),
            },
            "images": image_dicts,
            "count": len(image_dicts),
        }
    )


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
    return jsonify({"uuid": image.uuid, "customer_state": state.value})


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

    if library.finished_at is not None:
        return jsonify({"error": "Library is already marked as finished"}), 409

    liked_count = db.session.execute(
        select(db.func.count())
        .select_from(Image)
        .where(
            Image.library_id == library.id,
            Image.deleted_at.is_(None),
            Image.customer_state == CustomerState.liked,
        )
    ).scalar()

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
    db.session.commit()

    return jsonify(
        {
            "uuid": library.uuid,
            "finished_at": library.finished_at.isoformat(),
        }
    )
