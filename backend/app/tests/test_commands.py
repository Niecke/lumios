"""
Tests for Flask CLI commands (commands.py).

Covers the purge-deleted-accounts command:
- accounts past retention window are hard-deleted
- accounts within retention window are kept
- active (non-deleted) accounts are untouched
- all associated DB rows are removed (libraries, images, notifications, tickets)
- GCS delete_object is called for each image variant
- GCS failures do not abort DB deletion
"""

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
# GCS deletion
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
