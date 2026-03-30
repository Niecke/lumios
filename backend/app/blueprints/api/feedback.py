from flask import Blueprint, jsonify, request, g, current_app
from security import require_api_auth
from models import db, Feedback, User
from sqlalchemy import select, func

feedback_api = Blueprint("feedback_api", __name__, url_prefix="/feedback")

MAX_FEEDBACK_PER_USER = 100
MAX_BODY_LENGTH = 2000


@feedback_api.route("", methods=["POST"])
@require_api_auth
def submit_feedback():
    user_id = int(g.token_payload["sub"])

    count = (
        db.session.execute(
            select(func.count())
            .select_from(Feedback)
            .where(Feedback.user_id == user_id)
        ).scalar()
        or 0
    )

    if count >= MAX_FEEDBACK_PER_USER:
        return (
            jsonify({"error": "Unable to submit feedback. Please try again later."}),
            429,
        )

    data = request.get_json(silent=True) or {}
    rating = data.get("rating")
    body = (data.get("body") or "").strip() or None

    if rating is None:
        return jsonify({"error": "rating is required"}), 400
    if not isinstance(rating, int) or rating < 1 or rating > 5:
        return jsonify({"error": "rating must be an integer between 1 and 5"}), 400
    if body and len(body) > MAX_BODY_LENGTH:
        return (
            jsonify({"error": f"body must be {MAX_BODY_LENGTH} characters or fewer"}),
            400,
        )

    feedback = Feedback(user_id=user_id, rating=rating, body=body)
    db.session.add(feedback)
    db.session.commit()

    user = db.session.get(User, user_id)
    current_app.logger.info(
        "Feedback submitted: id=%d user=%s rating=%d",
        feedback.id,
        user.email if user else user_id,
        rating,
        extra={"log_type": "audit"},
    )

    return jsonify(feedback.to_dict()), 201
