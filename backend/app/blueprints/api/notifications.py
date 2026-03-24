from flask import Blueprint, jsonify, g
from security import require_api_auth, require_api_role
from models import db, Notification, NotificationType, Library, SupportTicket
from sqlalchemy import select, cast, String
from datetime import datetime, timezone

notifications_api = Blueprint(
    "notifications_api", __name__, url_prefix="/notifications"
)


@notifications_api.route("", methods=["GET"])
@require_api_auth
@require_api_role("photographer")
def list_notifications():
    user_id = int(g.token_payload["sub"])
    rows = db.session.execute(
        select(Notification, Library.name, SupportTicket.subject)
        .outerjoin(
            Library,
            (Library.uuid == Notification.related_object)
            & (Library.user_id == user_id),
        )
        .outerjoin(
            SupportTicket,
            (cast(SupportTicket.id, String) == Notification.related_object)
            & (Notification.type == NotificationType.ticket_comment_added)
            & (SupportTicket.user_id == user_id),
        )
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    ).all()

    result = []
    unseen_count = 0
    for n, library_name, ticket_subject in rows:
        entry = n.to_dict()
        if library_name:
            entry["library_name"] = library_name
        if ticket_subject:
            entry["ticket_subject"] = ticket_subject
        if n.seen_at is None:
            unseen_count += 1
        result.append(entry)

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
