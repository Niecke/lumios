"""
Tests for Flask CLI commands (commands.py).

Covers the purge-deleted-accounts command:
- accounts past retention window are hard-deleted
- accounts within retention window are kept
- active (non-deleted) accounts are untouched
- all associated DB rows are removed (libraries, images, notifications, tickets)
- Object storage delete_object is called for each image variant
- Object storage failures do not abort DB deletion
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from models import (
    db,
    User,
    Library,
    Image,
    Notification,
    NotificationType,
    SupportTicket,
    SupportTicketComment,
    Role,
    roles_users,
    AgbUpdate,
    AuditLog,
    AuditLogType,
)
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _soft_deleted_user(email: str, deleted_days_ago: int) -> User:
    user = User(email=email, active=False)
    user.set_password("TestPass123!")
    user.deleted_at = datetime.now(timezone.utc) - timedelta(days=deleted_days_ago)
    db.session.add(user)
    db.session.commit()
    return user


def _active_user(email: str) -> User:
    user = User(email=email, active=True)
    user.set_password("TestPass123!")
    db.session.add(user)
    db.session.commit()
    return user


def _make_library(user: User) -> Library:
    lib = Library(user_id=user.id, name="Test Library")
    db.session.add(lib)
    db.session.commit()
    return lib


def _make_image(library: Library) -> Image:
    img = Image(
        library_id=library.id,
        s3_key="abc123.jpg",
        original_filename="photo.jpg",
        content_type="image/jpeg",
        size=1024,
    )
    db.session.add(img)
    db.session.commit()
    return img


def _run_command(app):
    with patch("services.storage.delete_object"):
        runner = app.test_cli_runner()
        return runner.invoke(args=["purge-deleted-accounts"])


# ---------------------------------------------------------------------------
# Retention boundary
# ---------------------------------------------------------------------------


class TestRetentionBoundary:
    def test_purges_account_deleted_exactly_30_days_ago(self, app):
        user = _soft_deleted_user("old@test.com", deleted_days_ago=30)
        user_id = user.id

        with patch("services.storage.delete_object"):
            result = app.test_cli_runner().invoke(args=["purge-deleted-accounts"])

        assert result.exit_code == 0
        assert db.session.get(User, user_id) is None

    def test_purges_account_deleted_more_than_30_days_ago(self, app):
        user = _soft_deleted_user("older@test.com", deleted_days_ago=60)
        user_id = user.id

        with patch("services.storage.delete_object"):
            result = app.test_cli_runner().invoke(args=["purge-deleted-accounts"])

        assert result.exit_code == 0
        assert db.session.get(User, user_id) is None

    def test_keeps_account_deleted_29_days_ago(self, app):
        user = _soft_deleted_user("recent@test.com", deleted_days_ago=29)
        user_id = user.id

        result = _run_command(app)

        assert result.exit_code == 0
        assert db.session.get(User, user_id) is not None

    def test_keeps_active_user(self, app):
        user = _active_user("active@test.com")
        user_id = user.id

        result = _run_command(app)

        assert result.exit_code == 0
        assert db.session.get(User, user_id) is not None

    def test_no_accounts_exits_cleanly(self, app):
        with patch("services.storage.delete_object") as mock_del:
            result = app.test_cli_runner().invoke(args=["purge-deleted-accounts"])

        assert result.exit_code == 0
        mock_del.assert_not_called()


# ---------------------------------------------------------------------------
# DB cascade deletion
# ---------------------------------------------------------------------------


class TestDbCascade:
    def test_deletes_libraries_and_images(self, app):
        user = _soft_deleted_user("cascade@test.com", deleted_days_ago=31)
        lib = _make_library(user)
        img = _make_image(lib)
        lib_id, img_id = lib.id, img.id

        result = _run_command(app)

        assert result.exit_code == 0
        assert db.session.get(Library, lib_id) is None
        assert db.session.get(Image, img_id) is None

    def test_deletes_soft_deleted_libraries(self, app):
        user = _soft_deleted_user("softlib@test.com", deleted_days_ago=31)
        lib = _make_library(user)
        lib.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        lib_id = lib.id

        result = _run_command(app)

        assert result.exit_code == 0
        assert db.session.get(Library, lib_id) is None

    def test_deletes_notifications(self, app):
        user = _soft_deleted_user("notif@test.com", deleted_days_ago=31)
        notif = Notification(
            user_id=user.id,
            type=NotificationType.library_marked,
        )
        db.session.add(notif)
        db.session.commit()
        notif_id = notif.id

        result = _run_command(app)

        assert result.exit_code == 0
        assert db.session.get(Notification, notif_id) is None

    def test_deletes_support_tickets_and_comments(self, app):
        user = _soft_deleted_user("ticket@test.com", deleted_days_ago=31)
        ticket = SupportTicket(
            user_id=user.id, subject="Help", body="Please help"
        )
        db.session.add(ticket)
        db.session.commit()
        comment = SupportTicketComment(ticket_id=ticket.id, body="On it!")
        db.session.add(comment)
        db.session.commit()
        ticket_id, comment_id = ticket.id, comment.id

        result = _run_command(app)

        assert result.exit_code == 0
        assert db.session.get(SupportTicket, ticket_id) is None
        assert db.session.get(SupportTicketComment, comment_id) is None

    def test_removes_role_assignments(self, app):
        role = Role(name="photographer", description="Photographer")
        db.session.add(role)
        db.session.commit()

        user = _soft_deleted_user("roled@test.com", deleted_days_ago=31)
        user.roles.append(role)
        db.session.commit()
        user_id = user.id

        result = _run_command(app)

        assert result.exit_code == 0
        assert db.session.get(User, user_id) is None
        remaining = db.session.execute(
            select(roles_users).where(roles_users.c.user_id == user_id)
        ).fetchall()
        assert remaining == []


# ---------------------------------------------------------------------------
# Object storage deletion
# ---------------------------------------------------------------------------


class TestGcsDeletion:
    def test_deletes_all_three_variants(self, app):
        user = _soft_deleted_user("gcs@test.com", deleted_days_ago=31)
        lib = _make_library(user)
        img = _make_image(lib)

        with patch("services.storage.delete_object") as mock_del:
            app.test_cli_runner().invoke(args=["purge-deleted-accounts"])

        deleted_keys = {c.args[0] for c in mock_del.call_args_list}
        assert deleted_keys == {
            img.storage_path("originals"),
            img.storage_path("previews"),
            img.storage_path("thumbs"),
        }

    def test_deletes_library_cover(self, app):
        user = _soft_deleted_user("cover@test.com", deleted_days_ago=31)
        lib = _make_library(user)
        lib.cover_key = f"photos/{user.id}/{lib.id}/covers/cover-abcd1234.jpg"
        db.session.commit()

        with patch("services.storage.delete_object") as mock_del:
            app.test_cli_runner().invoke(args=["purge-deleted-accounts"])

        assert lib.cover_key in {c.args[0] for c in mock_del.call_args_list}

    def test_cover_delete_failure_does_not_abort_purge(self, app):
        user = _soft_deleted_user("coverfail@test.com", deleted_days_ago=31)
        lib = _make_library(user)
        lib.cover_key = f"photos/{user.id}/{lib.id}/covers/cover-abcd1234.jpg"
        db.session.commit()

        with patch("services.storage.delete_object", side_effect=Exception("S3 error")):
            app.test_cli_runner().invoke(args=["purge-deleted-accounts"])

        assert db.session.execute(select(Library).where(Library.user_id == user.id)).first() is None

    def test_gcs_failure_does_not_abort_db_deletion(self, app):
        user = _soft_deleted_user("gcsfail@test.com", deleted_days_ago=31)
        lib = _make_library(user)
        img = _make_image(lib)
        user_id, lib_id, img_id = user.id, lib.id, img.id

        with patch(
            "services.storage.delete_object", side_effect=Exception("GCS error")
        ):
            result = app.test_cli_runner().invoke(args=["purge-deleted-accounts"])

        assert result.exit_code == 0
        assert db.session.get(User, user_id) is None
        assert db.session.get(Library, lib_id) is None
        assert db.session.get(Image, img_id) is None

    def test_no_gcs_calls_when_library_has_no_images(self, app):
        user = _soft_deleted_user("noimg@test.com", deleted_days_ago=31)
        _make_library(user)

        with patch("services.storage.delete_object") as mock_del:
            app.test_cli_runner().invoke(args=["purge-deleted-accounts"])

        mock_del.assert_not_called()


# ---------------------------------------------------------------------------
# apply-agb-acceptance command
# ---------------------------------------------------------------------------


def _agb_update(version: str, effective_days_offset: int) -> AgbUpdate:
    """Create an AgbUpdate with effective_at = now + offset days."""
    update = AgbUpdate(
        version=version,
        summary=f"Changes for {version}",
        effective_at=datetime.now(timezone.utc) + timedelta(days=effective_days_offset),
    )
    db.session.add(update)
    db.session.commit()
    return update


def _run_apply_agb(app):
    runner = app.test_cli_runner()
    return runner.invoke(args=["apply-agb-acceptance"])


class TestApplyAgbAcceptance:
    def test_applies_past_due_update_to_active_users(self, app):
        user = _active_user("agb1@test.com")
        update = _agb_update("2.0", effective_days_offset=-1)

        result = _run_apply_agb(app)

        assert result.exit_code == 0
        db.session.refresh(user)
        assert user.agb_version == "2.0"
        assert user.agb_accepted_at is not None

        db.session.refresh(update)
        assert update.applied_at is not None

    def test_does_not_apply_future_update(self, app):
        user = _active_user("agb2@test.com")
        _agb_update("3.0", effective_days_offset=10)

        result = _run_apply_agb(app)

        assert result.exit_code == 0
        db.session.refresh(user)
        assert user.agb_version != "3.0"

    def test_does_not_apply_already_applied_update(self, app):
        user = _active_user("agb3@test.com")
        user.agb_version = "1.0"
        update = _agb_update("2.0", effective_days_offset=-1)
        update.applied_at = datetime.now(timezone.utc)
        db.session.commit()

        result = _run_apply_agb(app)

        assert result.exit_code == 0
        db.session.refresh(user)
        assert user.agb_version == "1.0"

    def test_does_not_update_deleted_users(self, app):
        user = _soft_deleted_user("agb4@test.com", deleted_days_ago=5)
        _agb_update("2.0", effective_days_offset=-1)

        result = _run_apply_agb(app)

        assert result.exit_code == 0
        db.session.refresh(user)
        assert user.agb_version != "2.0"

    def test_no_pending_updates_exits_cleanly(self, app):
        result = _run_apply_agb(app)
        assert result.exit_code == 0

    def test_accepted_at_matches_effective_date(self, app):
        user = _active_user("agb5@test.com")
        effective = datetime.now(timezone.utc) - timedelta(hours=6)
        update = AgbUpdate(
            version="2.1",
            summary="Test",
            effective_at=effective,
        )
        db.session.add(update)
        db.session.commit()

        _run_apply_agb(app)

        db.session.refresh(user)
        assert user.agb_accepted_at is not None
        # The column is timezone-naive; strip tz for comparison
        effective_naive = effective.replace(tzinfo=None)
        diff = abs((user.agb_accepted_at - effective_naive).total_seconds())
        assert diff < 2


# ---------------------------------------------------------------------------
# Sentry reporting on failure
# ---------------------------------------------------------------------------


class TestFailureReportedToSentry:
    @pytest.mark.parametrize(
        "command,target",
        [
            ("purge-deleted-accounts", "commands._purge_user"),
            ("purge-audit-logs", "commands.delete"),
            ("apply-agb-acceptance", "commands.select"),
        ],
    )
    def test_failure_captures_and_flushes(self, app, command, target):
        if command == "purge-deleted-accounts":
            _soft_deleted_user("sentryfail@test.com", deleted_days_ago=31)
        boom = RuntimeError("boom")
        with (
            patch(target, side_effect=boom),
            patch("commands.sentry_sdk") as sentry,
        ):
            result = app.test_cli_runner().invoke(args=[command])

        assert result.exit_code == 1
        sentry.capture_exception.assert_called_once_with(boom)
        sentry.flush.assert_called_once_with(timeout=2.0)


# ---------------------------------------------------------------------------
# create-admin-user / set-admin-password
# ---------------------------------------------------------------------------


def _invoke(app, args, stdin=""):
    return app.test_cli_runner().invoke(args=args, input=stdin)


def _reload(user_id):
    db.session.expire_all()
    return db.session.get(User, user_id)


def _admin_with_role(email="admin"):
    role = db.session.execute(select(Role).where(Role.name == "admin")).scalar_one_or_none()
    if role is None:
        role = Role(name="admin", description="Administrator")
        db.session.add(role)
    user = User(email=email, active=True)
    user.set_password("OldPassword1!")
    user.roles.append(role)
    db.session.add(user)
    db.session.commit()
    return user


def _password_from(output: str) -> str:
    return next(
        line.split(": ", 1)[1] for line in output.splitlines() if line.startswith("Password: ")
    )


class TestCreateAdminUser:
    def test_creates_admin_with_working_random_password(self, app):
        result = _invoke(app, ["create-admin-user", "--email", "new@test.com"])
        assert result.exit_code == 0
        password = _password_from(result.output)
        user = db.session.execute(select(User).where(User.email == "new@test.com")).scalar_one()
        assert user.active and user.account_type == "local"
        assert [r.name for r in user.roles] == ["admin"]
        assert user.verify_password(password)

    def test_each_password_differs_and_verifies(self, app):
        first = _password_from(_invoke(app, ["create-admin-user", "--email", "a@test.com"]).output)
        second = _password_from(_invoke(app, ["create-admin-user", "--email", "b@test.com"]).output)
        assert first != second
        a = db.session.execute(select(User).where(User.email == "a@test.com")).scalar_one()
        b = db.session.execute(select(User).where(User.email == "b@test.com")).scalar_one()
        assert a.verify_password(first) and b.verify_password(second)
        assert not a.verify_password(second)

    def test_existing_email_rejected_and_unchanged(self, app):
        user = _admin_with_role("dup@test.com")
        old_hash = user.auth_string
        result = _invoke(app, ["create-admin-user", "--email", "dup@test.com"])
        assert result.exit_code != 0
        assert "Password:" not in result.output
        assert _reload(user.id).auth_string == old_hash

    def test_existing_non_admin_email_rejected(self, app):
        user = _active_user("plain@test.com")
        result = _invoke(app, ["create-admin-user", "--email", "plain@test.com"])
        assert result.exit_code != 0
        assert _reload(user.id).roles == []

    def test_email_required(self, app):
        assert _invoke(app, ["create-admin-user"]).exit_code == 2


class TestSetAdminPassword:
    def test_resets_password_of_default_admin(self, app):
        user = _admin_with_role("admin")
        result = _invoke(app, ["set-admin-password"], "NewPassword1!\n")
        assert result.exit_code == 0
        user = _reload(user.id)
        assert user.verify_password("NewPassword1!")
        assert not user.verify_password("OldPassword1!")
        assert "NewPassword1!" not in result.output

    def test_second_run_replaces_first(self, app):
        user = _admin_with_role("admin")
        _invoke(app, ["set-admin-password"], "FirstPass123\n")
        _invoke(app, ["set-admin-password"], "SecondPass123\n")
        user = _reload(user.id)
        assert user.verify_password("SecondPass123")
        assert not user.verify_password("FirstPass123")

    def test_custom_email(self, app):
        user = _admin_with_role("boss@test.com")
        result = _invoke(app, ["set-admin-password", "--email", "boss@test.com"], "NewPassword1!\n")
        assert result.exit_code == 0
        assert _reload(user.id).verify_password("NewPassword1!")

    def test_admin_without_auth_string_gets_password(self, app):
        user = _admin_with_role("admin")
        user.auth_string = None
        db.session.commit()
        assert _invoke(app, ["set-admin-password"], "NewPassword1!\n").exit_code == 0
        assert _reload(user.id).verify_password("NewPassword1!")

    def test_short_password_rejected(self, app):
        user = _admin_with_role("admin")
        old_hash = user.auth_string
        result = _invoke(app, ["set-admin-password"], "short\n")
        assert result.exit_code != 0
        assert "short" not in result.output
        assert _reload(user.id).auth_string == old_hash

    def test_empty_stdin_rejected(self, app):
        user = _admin_with_role("admin")
        old_hash = user.auth_string
        assert _invoke(app, ["set-admin-password"], "").exit_code != 0
        assert _reload(user.id).auth_string == old_hash

    def test_unknown_email_rejected(self, app):
        result = _invoke(app, ["set-admin-password", "--email", "nobody@test.com"], "NewPassword1!\n")
        assert result.exit_code != 0
        assert db.session.execute(select(User).where(User.email == "nobody@test.com")).first() is None

    def test_user_without_admin_role_rejected(self, app):
        user = _active_user("plain@test.com")
        old_hash = user.auth_string
        result = _invoke(app, ["set-admin-password", "--email", "plain@test.com"], "NewPassword1!\n")
        assert result.exit_code != 0
        assert _reload(user.id).auth_string == old_hash

    def test_soft_deleted_admin_rejected(self, app):
        user = _admin_with_role("admin")
        user.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        old_hash = user.auth_string
        assert _invoke(app, ["set-admin-password"], "NewPassword1!\n").exit_code != 0
        assert _reload(user.id).auth_string == old_hash

    def test_audit_log_written_without_request_context(self, app):
        user = _admin_with_role("admin")
        _invoke(app, ["set-admin-password"], "NewPassword1!\n")
        entry = db.session.execute(
            select(AuditLog).where(AuditLog.audit_type == AuditLogType.password_set_by_admin)
        ).scalar_one()
        assert entry.creator_id == user.id
        assert entry.related_object_type == "user"
        assert entry.related_object_id == str(user.id)

    def test_tty_uses_hidden_prompt(self, app):
        user = _admin_with_role("admin")
        # CliRunner swaps sys.stdin while invoking, so replace the module's view of sys
        with patch("commands.sys") as fake_sys, patch(
            "commands.click.prompt", return_value="PromptPass123"
        ) as prompt:
            fake_sys.stdin.isatty.return_value = True
            result = _invoke(app, ["set-admin-password"])
        assert result.exit_code == 0
        kwargs = prompt.call_args.kwargs
        assert kwargs["hide_input"] is True and kwargs["confirmation_prompt"] is True
        assert _reload(user.id).verify_password("PromptPass123")

    def test_no_password_option(self, app):
        _admin_with_role("admin")
        result = _invoke(app, ["set-admin-password", "--password", "NewPassword1!"])
        assert result.exit_code == 2
