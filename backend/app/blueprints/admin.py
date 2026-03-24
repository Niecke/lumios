from flask import (
    Blueprint,
    render_template,
    request,
    flash,
    redirect,
    url_for,
    current_app,
)
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from models import db, User, Role, Library, Image, SupportTicket, SupportTicketComment, SupportTicketStatus, Notification, NotificationType
from security import login_required, require_role

admin = Blueprint("admin", __name__)


@admin.route("/")
@login_required
@require_role("admin")
def index():
    library_count = db.session.scalar(
        select(func.count(Library.id)).where(Library.deleted_at.is_(None))
    )
    image_count, total_size = db.session.execute(
        select(func.count(Image.id), func.coalesce(func.sum(Image.size), 0)).where(
            Image.deleted_at.is_(None)
        )
    ).one()
    return render_template(
        "index.html",
        library_count=library_count,
        image_count=image_count,
        total_size=total_size,
    )


@admin.route("/admin/dashboard", methods=["GET", "POST"])
@login_required
@require_role("admin")
def dashboard():
    users = (
        db.session.execute(
            select(User)
            .where(User.deleted_at.is_(None))
            .options(selectinload(User.roles))
        )
        .scalars()
        .all()
    )

    # Per-user stats: libraries, photos, total size
    rows = db.session.execute(
        select(
            Library.user_id,
            func.count(func.distinct(Library.id)),
            func.count(Image.id),
            func.coalesce(func.sum(Image.size), 0),
        )
        .outerjoin(Image, (Image.library_id == Library.id) & Image.deleted_at.is_(None))
        .where(Library.deleted_at.is_(None))
        .group_by(Library.user_id)
    ).all()
    user_stats = {
        uid: {"libraries": libs, "photos": imgs, "total_size": size}
        for uid, libs, imgs, size in rows
    }

    return render_template("admin/dashboard.html", users=users, user_stats=user_stats)


@admin.route("/admin/user_create", methods=["GET", "POST"])
@login_required
@require_role("admin")
def user_create():
    all_roles = db.session.execute(select(Role)).scalars().all()

    if request.method == "POST":
        email = request.form["email"]
        account_type = request.form.get("account_type", "local")
        active = "active" in request.form

        if account_type not in ("local", "google"):
            flash("Invalid account type.", "error")
            return render_template("admin/user_create.html", email=email, all_roles=all_roles)

        # Check if user exists
        if db.session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none():
            flash("Email already exists!", "error")
            return render_template("admin/user_create.html", email=email, all_roles=all_roles)

        user = User(email=email, active=active, account_type=account_type)

        if account_type == "local":
            password = request.form.get("password", "")
            try:
                user.set_password(password)
            except ValueError as ex:
                flash(str(ex), "error")
                return render_template("admin/user_create.html", email=email, all_roles=all_roles)

        selected_role_ids = set(int(r) for r in request.form.getlist("roles"))
        user.roles = [r for r in all_roles if r.id in selected_role_ids]

        db.session.add(user)
        db.session.commit()

        current_app.logger.info(
            "User created: %s (%s)", email, account_type, extra={"log_type": "audit"}
        )
        flash(f'User "{email}" created successfully!', "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/user_create.html", all_roles=all_roles)


@admin.route("/admin/user_edit/<int:id>", methods=["GET", "POST"])
@login_required
@require_role("admin")
def user_edit(id):
    user = db.session.get(User, id)

    if not user:
        flash(f'User ID "{id}" unknown!', "error")
        return redirect(url_for("admin.dashboard"))

    all_roles = db.session.execute(select(Role)).scalars().all()

    if request.method == "POST":
        submitted_email = request.form.get("email", "").strip()
        if user.is_system and submitted_email and submitted_email != user.email:
            flash("The email of a system user cannot be changed.", "error")
            return render_template(
                "admin/user_edit.html", user=user, all_roles=all_roles
            )

        password = request.form.get("password", "").strip()
        active = "active" in request.form
        selected_role_ids = set(int(r) for r in request.form.getlist("roles"))

        changes = []
        if password:
            try:
                user.set_password(password)
            except ValueError as ex:
                flash(str(ex), "error")
                return render_template(
                    "admin/user_edit.html", user=user, all_roles=all_roles
                )
            changes.append("password")

        if active != user.active:
            changes.append(f"active={active}")
        user.active = active

        new_roles = [r for r in all_roles if r.id in selected_role_ids]
        if set(r.id for r in user.roles) != selected_role_ids:
            changes.append("roles")
        user.roles = new_roles

        db.session.commit()

        current_app.logger.info(
            "User updated: %s (changed: %s)",
            user.email,
            ", ".join(changes) or "none",
            extra={"log_type": "audit"},
        )
        flash(f'User "{user.email}" updated successfully!', "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/user_edit.html", user=user, all_roles=all_roles)


@admin.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    from current_user import current_user

    user = db.session.get(User, current_user.id)
    if user.account_type != "local":
        flash("Password change is only available for local accounts.", "error")
        return redirect(url_for("admin.index"))

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not user.verify_password(current_password):
            flash("Current password is incorrect.", "error")
            return render_template("change_password.html")

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return render_template("change_password.html")

        try:
            user.set_password(new_password)
        except ValueError as ex:
            flash(str(ex), "error")
            return render_template("change_password.html")

        db.session.commit()
        current_app.logger.info(
            "Password changed: %s (self)", user.email, extra={"log_type": "audit"}
        )
        flash("Password changed successfully!", "success")
        return redirect(url_for("admin.index"))

    return render_template("change_password.html")


@admin.route("/admin/set_password/<int:id>", methods=["GET", "POST"])
@login_required
@require_role("admin")
def set_password(id):
    user = db.session.get(User, id)
    if not user:
        flash(f'User ID "{id}" unknown!', "error")
        return redirect(url_for("admin.dashboard"))

    if user.account_type != "local":
        flash("Password can only be set for local accounts.", "error")
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("admin/set_password.html", user=user)

        try:
            user.set_password(new_password)
        except ValueError as ex:
            flash(str(ex), "error")
            return render_template("admin/set_password.html", user=user)

        db.session.commit()
        current_app.logger.info(
            "Password set by admin for: %s", user.email, extra={"log_type": "audit"}
        )
        flash(f'Password for "{user.email}" updated successfully!', "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/set_password.html", user=user)


@admin.route("/admin/user_delete/<int:id>", methods=["POST"])
@login_required
@require_role("admin")
def user_delete(id):
    user = db.session.get(User, id)

    if not user:
        flash(f'User ID "{id}" unknown!', "error")
        return redirect(url_for("admin.dashboard"))

    if user.is_system:
        flash("System users cannot be deleted.", "error")
        return redirect(url_for("admin.dashboard"))

    user.deleted_at = datetime.now(timezone.utc)
    user.active = False
    db.session.commit()

    current_app.logger.info("User soft-deleted: %s", user.email, extra={"log_type": "audit"})
    flash(f'User "{user.email}" deleted!', "success")
    return redirect(url_for("admin.dashboard"))


# ---------------------------------------------------------------------------
# Support ticket management (admin only)
# ---------------------------------------------------------------------------


@admin.route("/admin/support", methods=["GET"])
@login_required
@require_role("admin")
def support_list():
    tickets = (
        db.session.execute(
            select(SupportTicket)
            .options(selectinload(SupportTicket.user), selectinload(SupportTicket.comments))
            .order_by(
                # open tickets first, then by newest
                SupportTicket.status.asc(),
                SupportTicket.created_at.desc(),
            )
        )
        .scalars()
        .all()
    )
    return render_template("admin/support_list.html", tickets=tickets)


@admin.route("/admin/support/<int:ticket_id>", methods=["GET"])
@login_required
@require_role("admin")
def support_detail(ticket_id: int):
    ticket = db.session.execute(
        select(SupportTicket)
        .where(SupportTicket.id == ticket_id)
        .options(selectinload(SupportTicket.user), selectinload(SupportTicket.comments))
    ).scalar_one_or_none()

    if ticket is None:
        flash("Ticket not found.", "error")
        return redirect(url_for("admin.support_list"))

    return render_template("admin/support_detail.html", ticket=ticket)


@admin.route("/admin/support/<int:ticket_id>/comment", methods=["POST"])
@login_required
@require_role("admin")
def support_add_comment(ticket_id: int):
    ticket = db.session.get(SupportTicket, ticket_id)
    if ticket is None:
        flash("Ticket not found.", "error")
        return redirect(url_for("admin.support_list"))

    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Comment body is required.", "error")
        return redirect(url_for("admin.support_detail", ticket_id=ticket_id))

    comment = SupportTicketComment(ticket_id=ticket_id, body=body)
    db.session.add(comment)

    if request.form.get("close") == "on":
        ticket.status = SupportTicketStatus.closed
        ticket.updated_at = datetime.now(timezone.utc)
        current_app.logger.info(
            "Support ticket #%d closed by admin with comment", ticket_id,
            extra={"log_type": "audit"},
        )
    else:
        ticket.updated_at = datetime.now(timezone.utc)

    notification = Notification(
        user_id=ticket.user_id,
        type=NotificationType.ticket_comment_added,
        related_object=str(ticket.id),
    )
    db.session.add(notification)

    db.session.commit()
    flash("Comment added.", "success")
    return redirect(url_for("admin.support_detail", ticket_id=ticket_id))


@admin.route("/admin/support/<int:ticket_id>/close", methods=["POST"])
@login_required
@require_role("admin")
def support_close(ticket_id: int):
    ticket = db.session.get(SupportTicket, ticket_id)
    if ticket is None:
        flash("Ticket not found.", "error")
        return redirect(url_for("admin.support_list"))

    ticket.status = SupportTicketStatus.closed
    ticket.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    current_app.logger.info(
        "Support ticket #%d closed by admin", ticket_id, extra={"log_type": "audit"}
    )
    flash("Ticket closed.", "success")
    return redirect(url_for("admin.support_detail", ticket_id=ticket_id))
