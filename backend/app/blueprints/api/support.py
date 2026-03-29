from flask import Blueprint, jsonify, request, g, current_app
from security import require_api_auth
from models import db, SupportTicket, SupportTicketStatus, SupportTicketComment, User
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from services.mail import notify_new_support_ticket

support_api = Blueprint("support_api", __name__, url_prefix="/support")

MAX_SUBJECT_LENGTH = 255
MAX_OPEN_TICKETS = 100
MAX_BODY_LENGTH = 10000


@support_api.route("/tickets", methods=["GET"])
@require_api_auth
def list_tickets():
    user_id = int(g.token_payload["sub"])
    tickets = (
        db.session.execute(
            select(SupportTicket)
            .where(SupportTicket.user_id == user_id)
            .options(selectinload(SupportTicket.comments))
            .order_by(SupportTicket.created_at.desc())
        )
        .scalars()
        .all()
    )
    return jsonify({"tickets": [t.to_dict() for t in tickets]})


@support_api.route("/tickets", methods=["POST"])
@require_api_auth
def create_ticket():
    user_id = int(g.token_payload["sub"])

    # Silently enforce open ticket limit to prevent abuse
    open_count = db.session.execute(
        select(func.count())
        .select_from(SupportTicket)
        .where(
            SupportTicket.user_id == user_id,
            SupportTicket.status == SupportTicketStatus.open,
        )
    ).scalar()

    if open_count >= MAX_OPEN_TICKETS:
        return (
            jsonify({"error": "Unable to submit ticket. Please try again later."}),
            429,
        )

    data = request.get_json(silent=True) or {}
    subject = (data.get("subject") or "").strip()
    body = (data.get("body") or "").strip()

    if not subject:
        return jsonify({"error": "subject is required"}), 400
    if len(subject) > MAX_SUBJECT_LENGTH:
        return (
            jsonify(
                {"error": f"subject must be {MAX_SUBJECT_LENGTH} characters or fewer"}
            ),
            400,
        )
    if not body:
        return jsonify({"error": "body is required"}), 400
    if len(body) > MAX_BODY_LENGTH:
        return (
            jsonify({"error": f"body must be {MAX_BODY_LENGTH} characters or fewer"}),
            400,
        )

    ticket = SupportTicket(user_id=user_id, subject=subject, body=body)
    db.session.add(ticket)
    db.session.commit()

    user = db.session.get(User, user_id)
    current_app.logger.info(
        "Support ticket created: id=%d user=%s",
        ticket.id,
        user.email if user else user_id,
        extra={"log_type": "audit"},
    )

    notify_new_support_ticket(
        ticket_id=ticket.id,
        subject=ticket.subject,
        user_email=user.email if user else str(user_id),
    )

    return jsonify(ticket.to_dict()), 201


@support_api.route("/tickets/<int:ticket_id>", methods=["GET"])
@require_api_auth
def get_ticket(ticket_id: int):
    user_id = int(g.token_payload["sub"])
    ticket = db.session.execute(
        select(SupportTicket)
        .where(SupportTicket.id == ticket_id, SupportTicket.user_id == user_id)
        .options(selectinload(SupportTicket.comments))
    ).scalar_one_or_none()

    if ticket is None:
        return jsonify({"error": "Ticket not found"}), 404

    return jsonify(ticket.to_dict())
