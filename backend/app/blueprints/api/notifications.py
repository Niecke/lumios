from flask import Blueprint, jsonify, g
from security import require_api_auth, require_api_role
from models import db, Notification, Library
from sqlalchemy import select
from datetime import datetime, timezone

notifications_api = Blueprint(
    "notifications_api", __name__, url_prefix="/notifications"
)


@notifications_api.route("", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def list_notifications():
    user_id = int(g.token_payload["sub"])
    notifications = (
        db.session.execute(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )

    result = []
    for n in notifications:
        entry = n.to_dict()
        if n.related_object:
            library = db.session.execute(
                select(Library).where(Library.uuid == n.related_object)
            ).scalar_one_or_none()
            if library:
                entry["library_name"] = library.name
        result.append(entry)

    unseen_count = sum(1 for n in notifications if n.seen_at is None)

    return jsonify({
        "notifications": result,
        "unseen_count": unseen_count,
    })


@notifications_api.route("/<int:notification_id>/seen", methods=["PATCH"])
@require_api_auth
@require_api_role("photographer")
def mark_seen(notification_id: int):
    user_id = int(g.token_payload["sub"])
    notification = db.session.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    ).scalar_one_or_none()
    if notification is None:
        return jsonify({"error": "Notification not found"}), 404

    if notification.seen_at is None:
        notification.seen_at = datetime.now(timezone.utc)
        db.session.commit()

    return jsonify(notification.to_dict())
