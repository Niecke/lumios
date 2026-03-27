from flask import Blueprint, jsonify, request, current_app
from main import limiter
from models import (
    db,
    Library,
    Image,
    CustomerState,
    Notification,
    NotificationType,
    User,
    Waitlist,
)
from sqlalchemy import select, func, or_
from services import storage
from services.mail import notify_gallery_finished, add_to_brevo_waitlist
from config import MAX_USERS, BREVO_WAITLIST_LIST_ID, REDIS_URL
from datetime import datetime, timezone, date
import re
import json
import hashlib

if REDIS_URL:
    import redis as _redis_module
    _redis = _redis_module.from_url(REDIS_URL, decode_responses=True)
else:
    _redis = None

public_api = Blueprint("public_api", __name__, url_prefix="/public")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _record_library_view(library: Library) -> None:
    """Update last_viewed_at and fire a notification the first time a given
    visitor IP sees this library today. Silently skips if Redis is unavailable."""
    library.last_viewed_at = datetime.now(timezone.utc)

    if _redis is None:
        return

    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "")
    today = date.today().isoformat()
    visitor_hash = hashlib.sha256(f"{ip}:{today}".encode()).hexdigest()[:16]
    redis_key = f"library:viewed:{library.id}:{visitor_hash}"

    try:
        is_new = _redis.set(redis_key, 1, nx=True, ex=86400)
    except Exception:
        return  # Redis unavailable — skip notification, last_viewed_at already set

    if is_new:
        notification = Notification(
            type=NotificationType.library_viewed,
            user_id=library.user_id,
            related_object=library.uuid,
        )
        db.session.add(notification)


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

    _record_library_view(library)

    images = (
        db.session.execute(
            select(Image)
            .where(Image.library_id == library.id, Image.deleted_at.is_(None))
            .order_by(Image.created_at.desc())
        )
        .scalars()
        .all()
    )

    preview_variant = "originals" if library.use_original_as_preview else "previews"
    image_dicts = [
        {
            "uuid": img.uuid,
            "filename": img.original_filename,
            "width": img.width,
            "height": img.height,
            "customer_state": img.customer_state.value,
            "preview_url": storage.get_presigned_url(img.storage_path(preview_variant)),
            "thumb_url": storage.get_presigned_url(img.storage_path("thumbs")),
            "download_url": storage.get_presigned_download_url(
                img.storage_path(preview_variant), img.original_filename
            ) if library.download_enabled else None,
        }
        for img in images
    ]

    db.session.commit()

    return jsonify(
        {
            "library": {
                "uuid": library.uuid,
                "name": library.name,
                "finished_at": (
                    library.finished_at.isoformat() if library.finished_at else None
                ),
                "use_original_as_preview": library.use_original_as_preview,
                "download_enabled": library.download_enabled,
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

    liked_count = (
        db.session.execute(
            select(db.func.count())
            .select_from(Image)
            .where(
                Image.library_id == library.id,
                Image.deleted_at.is_(None),
                Image.customer_state == CustomerState.liked,
            )
        ).scalar()
        or 0
    )

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


@public_api.route("/registration_status", methods=["GET"])
@limiter.limit("30 per minute")
def registration_status():
    """Return whether new registrations are currently open."""
    slot_count = (
        db.session.execute(
            select(func.count(User.id)).where(
                or_(User.active.is_(True), User.activation_pending.is_(True)),
                User.deleted_at.is_(None),
            )
        ).scalar()
        or 0
    )
    return jsonify({"can_register": slot_count < MAX_USERS})


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

    # Store locally so admins can see waitlist entries even without Brevo configured
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
    """Receive a JavaScript error report from the browser and forward it to
    Cloud Error Reporting via a structured Cloud Logging entry.

    The entry format matches the ReportedErrorEvent schema so that Cloud
    Logging automatically ingests it into Cloud Error Reporting without
    requiring the google-cloud-error-reporting library.
    """
    data = request.get_json(silent=True) or {}

    message = str(data.get("message") or "Unknown error")[:2000]
    stack = str(data.get("stack") or "")[:5000]
    url = str(data.get("url") or "")[:500]
    line_number = int(data.get("line_number") or 0)
    col_number = int(data.get("col_number") or 0)
    user_agent = request.headers.get("User-Agent", "")[:500]

    # Write structured JSON directly to stdout so Cloud Run's log agent parses
    # it as jsonPayload rather than textPayload. The @type field must be at the
    # top level of jsonPayload for Cloud Error Reporting to ingest the entry.
    # See: https://cloud.google.com/error-reporting/docs/formatting-error-messages
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
