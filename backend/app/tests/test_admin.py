"""
Tests for the admin blueprint: users, user_create, user_delete, user_edit.
"""

import io
import json
import zipfile

import pytest
from datetime import datetime, timezone, timedelta
from html import unescape
from unittest.mock import patch
from conftest import do_login
from models import db, User, AgbUpdate, AuditLog, AuditLogType
from sqlalchemy import select, func


def html_text(response):
    """Decode response body and unescape HTML entities (e.g. &#34; → ")."""
    return unescape(response.data.decode())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def login_admin(client, admin_user):
    do_login(client, "admin@test.com", "AdminPass123!")


def login_regular(client, regular_user):
    do_login(client, "user@test.com", "UserPass123!")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class TestAdminDashboard:
    def test_users_requires_login(self, client):
        response = client.get("/admin/users", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location

    def test_users_requires_admin_role(self, client, regular_user):
        login_regular(client, regular_user)
        response = client.get("/admin/users", follow_redirects=True)
        # Should redirect to index with error flash, not show users
        assert response.status_code == 200
        html = html_text(response)
        assert "Access denied." in html

    def test_users_accessible_to_admin(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.get("/admin/users")
        assert response.status_code == 200

    def test_users_lists_users(self, client, admin_user, regular_user):
        login_admin(client, admin_user)
        response = client.get("/admin/users")
        html = response.data.decode()
        assert "admin@test.com" in html
        assert "user@test.com" in html


# ---------------------------------------------------------------------------
# User create
# ---------------------------------------------------------------------------


class TestAdminUserCreate:
    def test_user_create_requires_login(self, client):
        response = client.get("/admin/user_create", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location

    def test_user_create_get_shows_form(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.get("/admin/user_create")
        assert response.status_code == 200
        html = response.data.decode()
        assert "email" in html.lower()
        assert "password" in html.lower()

    def test_user_create_post_valid_creates_user(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.post(
            "/admin/user_create",
            data={
                "email": "newuser@test.com",
                "password": "NewUserPass1!",
                "active": "on",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        html = html_text(response)
        assert 'User "newuser@test.com" created successfully!' in html

        # Verify the user actually exists in the database
        from sqlalchemy import select

        user = db.session.execute(
            select(User).where(User.email == "newuser@test.com")
        ).scalar_one_or_none()
        assert user is not None
        assert user.active is True

    def test_user_create_post_inactive_user(self, client, admin_user):
        login_admin(client, admin_user)
        client.post(
            "/admin/user_create",
            data={"email": "inactive_new@test.com", "password": "SomePass1!"},
            follow_redirects=True,
        )
        from sqlalchemy import select

        user = db.session.execute(
            select(User).where(User.email == "inactive_new@test.com")
        ).scalar_one_or_none()
        assert user is not None
        assert user.active is False  # 'active' not in form data

    def test_user_create_duplicate_email_shows_error(
        self, client, admin_user, regular_user
    ):
        login_admin(client, admin_user)
        response = client.post(
            "/admin/user_create",
            data={"email": "user@test.com", "password": "SomePass1!"},
            follow_redirects=True,
        )
        html = response.data.decode()
        assert "Email already exists!" in html

    def test_user_create_password_too_short_shows_error(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.post(
            "/admin/user_create",
            data={"email": "short@test.com", "password": "short"},
            follow_redirects=True,
        )
        # Should stay on the create page with a validation error
        assert response.status_code == 200
        html = response.data.decode()
        # The ValueError message from set_password is flashed
        assert "Password needs to be longer than" in html or "error" in html.lower()

    def test_user_create_preserves_email_on_password_error(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.post(
            "/admin/user_create",
            data={"email": "preserved@test.com", "password": "sh"},
            follow_redirects=True,
        )
        html = response.data.decode()
        assert "preserved@test.com" in html

    def test_user_create_requires_admin_role(self, client, regular_user):
        login_regular(client, regular_user)
        response = client.get("/admin/user_create", follow_redirects=True)
        html = html_text(response)
        assert "Access denied." in html


# ---------------------------------------------------------------------------
# User delete
# ---------------------------------------------------------------------------


class TestAdminUserDelete:
    def test_user_delete_requires_login(self, client, regular_user):
        response = client.post(
            f"/admin/user_delete/{regular_user.id}", follow_redirects=False
        )
        assert response.status_code == 302
        assert "/login" in response.location

    def test_user_delete_requires_admin_role(self, client, regular_user):
        login_regular(client, regular_user)
        response = client.post(
            f"/admin/user_delete/{regular_user.id}", follow_redirects=True
        )
        html = html_text(response)
        assert "Access denied." in html

    def test_user_delete_removes_user(self, client, admin_user, regular_user):
        user_id = regular_user.id
        login_admin(client, admin_user)
        response = client.post(f"/admin/user_delete/{user_id}", follow_redirects=True)
        assert response.status_code == 200
        html = response.data.decode()
        assert "deleted!" in html

        # Confirm user is soft-deleted
        user = db.session.get(User, user_id)
        assert user is not None
        assert user.deleted_at is not None
        assert user.active is False

    def test_user_delete_unknown_id_shows_error(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.post("/admin/user_delete/99999", follow_redirects=True)
        html = response.data.decode()
        assert "unknown" in html

    def test_user_delete_system_user_blocked(self, client, admin_user):
        protected = User(email="system@test.com", active=True, is_system=True)
        protected.set_password("ProtectedPass1!")
        db.session.add(protected)
        db.session.commit()

        login_admin(client, admin_user)
        response = client.post(
            f"/admin/user_delete/{protected.id}", follow_redirects=True
        )
        html = response.data.decode()
        assert "System users cannot be deleted." in html
        # Confirm user still exists
        assert db.session.get(User, protected.id) is not None

    def test_user_delete_requires_post(self, client, admin_user, regular_user):
        login_admin(client, admin_user)
        response = client.get(f"/admin/user_delete/{regular_user.id}")
        assert response.status_code == 405


# ---------------------------------------------------------------------------
# User edit
# ---------------------------------------------------------------------------


class TestAdminUserEdit:
    def test_user_edit_requires_login(self, client):
        response = client.get("/admin/user_edit/1", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location

    def test_user_edit_requires_admin_role(self, client, regular_user):
        login_regular(client, regular_user)
        response = client.get(
            f"/admin/user_edit/{regular_user.id}", follow_redirects=True
        )
        html = html_text(response)
        assert "Access denied." in html

    def test_user_edit_get_shows_form(self, client, admin_user, regular_user):
        login_admin(client, admin_user)
        response = client.get(f"/admin/user_edit/{regular_user.id}")
        assert response.status_code == 200
        html = response.data.decode()
        assert "password" in html.lower()
        assert "active" in html.lower()

    def test_user_edit_get_shows_email_as_readonly(
        self, client, admin_user, regular_user
    ):
        login_admin(client, admin_user)
        response = client.get(f"/admin/user_edit/{regular_user.id}")
        html = response.data.decode()
        assert "user@test.com" in html
        # email field must be disabled, not a writable input
        assert "disabled" in html

    def test_user_edit_unknown_id_redirects_with_error(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.get("/admin/user_edit/99999", follow_redirects=True)
        html = html_text(response)
        assert "unknown" in html

    def test_user_edit_changes_password(self, client, admin_user, regular_user):
        login_admin(client, admin_user)
        client.post(
            f"/admin/user_edit/{regular_user.id}",
            data={"password": "NewPassword1!", "active": "on"},
            follow_redirects=True,
        )
        db.session.refresh(regular_user)
        assert regular_user.verify_password("NewPassword1!")

    def test_user_edit_old_password_no_longer_works(
        self, client, admin_user, regular_user
    ):
        login_admin(client, admin_user)
        client.post(
            f"/admin/user_edit/{regular_user.id}",
            data={"password": "NewPassword1!", "active": "on"},
            follow_redirects=True,
        )
        db.session.refresh(regular_user)
        assert not regular_user.verify_password("UserPass123!")

    def test_user_edit_blank_password_keeps_existing(
        self, client, admin_user, regular_user
    ):
        login_admin(client, admin_user)
        client.post(
            f"/admin/user_edit/{regular_user.id}",
            data={"password": "", "active": "on"},
            follow_redirects=True,
        )
        db.session.refresh(regular_user)
        assert regular_user.verify_password("UserPass123!")

    def test_user_edit_deactivates_user(self, client, admin_user, regular_user):
        login_admin(client, admin_user)
        client.post(
            f"/admin/user_edit/{regular_user.id}",
            data={"password": ""},  # 'active' absent → False
            follow_redirects=True,
        )
        db.session.refresh(regular_user)
        assert regular_user.active is False

    def test_user_edit_activates_user(self, client, admin_user, inactive_user):
        login_admin(client, admin_user)
        client.post(
            f"/admin/user_edit/{inactive_user.id}",
            data={"password": "", "active": "on"},
            follow_redirects=True,
        )
        db.session.refresh(inactive_user)
        assert inactive_user.active is True

    def test_user_edit_does_not_change_email(self, client, admin_user, regular_user):
        login_admin(client, admin_user)
        client.post(
            f"/admin/user_edit/{regular_user.id}",
            data={"email": "hacked@evil.com", "password": "", "active": "on"},
            follow_redirects=True,
        )
        db.session.refresh(regular_user)
        assert regular_user.email == "user@test.com"

    def test_user_edit_system_user_email_change_blocked(self, client, admin_user):
        system = User(email="system@test.com", active=True, is_system=True)
        system.set_password("SystemPass1!")
        db.session.add(system)
        db.session.commit()

        login_admin(client, admin_user)
        response = client.post(
            f"/admin/user_edit/{system.id}",
            data={"email": "changed@evil.com", "password": "", "active": "on"},
            follow_redirects=True,
        )
        html = html_text(response)
        assert "email of a system user cannot be changed" in html
        db.session.refresh(system)
        assert system.email == "system@test.com"

    def test_user_edit_short_password_shows_error(
        self, client, admin_user, regular_user
    ):
        login_admin(client, admin_user)
        response = client.post(
            f"/admin/user_edit/{regular_user.id}",
            data={"password": "short", "active": "on"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        html = response.data.decode()
        assert "Password needs to be longer than" in html

    def test_user_edit_short_password_does_not_change_password(
        self, client, admin_user, regular_user
    ):
        login_admin(client, admin_user)
        client.post(
            f"/admin/user_edit/{regular_user.id}",
            data={"password": "short", "active": "on"},
            follow_redirects=True,
        )
        db.session.refresh(regular_user)
        assert regular_user.verify_password("UserPass123!")

    def test_user_edit_success_shows_flash(self, client, admin_user, regular_user):
        login_admin(client, admin_user)
        response = client.post(
            f"/admin/user_edit/{regular_user.id}",
            data={"password": "", "active": "on"},
            follow_redirects=True,
        )
        html = html_text(response)
        assert "updated successfully!" in html


# ---------------------------------------------------------------------------
# GDPR export
# ---------------------------------------------------------------------------


class TestAdminGdprExport:

    def test_gdpr_export_requires_login(self, client, regular_user):
        resp = client.post(
            f"/admin/user_gdpr_export/{regular_user.id}",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.location

    def test_gdpr_export_requires_admin_role(self, client, regular_user):
        login_regular(client, regular_user)
        resp = client.post(
            f"/admin/user_gdpr_export/{regular_user.id}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        html = html_text(resp)
        assert "Access denied." in html

    def test_gdpr_export_unknown_user_shows_error(self, client, admin_user):
        login_admin(client, admin_user)
        resp = client.post(
            "/admin/user_gdpr_export/99999",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        html = html_text(resp)
        assert "not found" in html

    def test_gdpr_export_creates_valid_zip(
        self, client, admin_user, regular_user, monkeypatch
    ):
        login_admin(client, admin_user)
        uploaded = {}

        def mock_upload(file_obj, key, content_type):
            uploaded["key"] = key
            uploaded["data"] = file_obj.read()

        monkeypatch.setattr("blueprints.admin.storage.upload_fileobj", mock_upload)

        resp = client.post(
            f"/admin/user_gdpr_export/{regular_user.id}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "key" in uploaded, "upload_fileobj was not called"

        zf = zipfile.ZipFile(io.BytesIO(uploaded["data"]))
        names = zf.namelist()
        assert "user.json" in names
        assert "libraries.json" in names
        assert "images.json" in names
        assert "audit_logs.json" in names
        assert "support_tickets.json" in names
        assert "notifications.json" in names

    def test_gdpr_export_user_json_contains_email(
        self, client, admin_user, regular_user, monkeypatch
    ):
        login_admin(client, admin_user)
        uploaded = {}

        def mock_upload(file_obj, key, content_type):
            uploaded["key"] = key
            uploaded["data"] = file_obj.read()

        monkeypatch.setattr("blueprints.admin.storage.upload_fileobj", mock_upload)

        client.post(
            f"/admin/user_gdpr_export/{regular_user.id}",
            follow_redirects=True,
        )

        zf = zipfile.ZipFile(io.BytesIO(uploaded["data"]))
        user_json = json.loads(zf.read("user.json"))
        assert user_json["email"] == "user@test.com"
        assert user_json["id"] == regular_user.id
        assert "auth_string" not in user_json

    def test_gdpr_export_user_json_omits_legacy_quota_columns(
        self, client, admin_user, regular_user, monkeypatch
    ):
        login_admin(client, admin_user)
        uploaded = {}

        def mock_upload(file_obj, key, content_type):
            uploaded["data"] = file_obj.read()

        monkeypatch.setattr("blueprints.admin.storage.upload_fileobj", mock_upload)

        client.post(
            f"/admin/user_gdpr_export/{regular_user.id}",
            follow_redirects=True,
        )

        zf = zipfile.ZipFile(io.BytesIO(uploaded["data"]))
        user_json = json.loads(zf.read("user.json"))
        assert "max_libraries" not in user_json
        assert "max_images_per_library" not in user_json

    def test_gdpr_export_s3_key_format(
        self, client, admin_user, regular_user, monkeypatch
    ):
        login_admin(client, admin_user)
        uploaded = {}

        def mock_upload(file_obj, key, content_type):
            uploaded["key"] = key
            uploaded["data"] = file_obj.read()

        monkeypatch.setattr("blueprints.admin.storage.upload_fileobj", mock_upload)

        client.post(
            f"/admin/user_gdpr_export/{regular_user.id}",
            follow_redirects=True,
        )

        assert uploaded["key"].startswith(f"gdpr-exports/{regular_user.id}/")
        assert uploaded["key"].endswith(".zip")

    def test_gdpr_export_flashes_s3_key(
        self, client, admin_user, regular_user, monkeypatch
    ):
        login_admin(client, admin_user)

        def mock_upload(file_obj, key, content_type):
            pass

        monkeypatch.setattr("blueprints.admin.storage.upload_fileobj", mock_upload)

        resp = client.post(
            f"/admin/user_gdpr_export/{regular_user.id}",
            follow_redirects=True,
        )
        html = html_text(resp)
        assert f"gdpr-exports/{regular_user.id}/" in html

    def test_gdpr_export_works_for_soft_deleted_user(
        self, client, admin_user, regular_user, monkeypatch
    ):
        from datetime import datetime, timezone

        regular_user.deleted_at = datetime.now(timezone.utc)
        db.session.commit()

        login_admin(client, admin_user)
        uploaded = {}

        def mock_upload(file_obj, key, content_type):
            uploaded["key"] = key
            uploaded["data"] = file_obj.read()

        monkeypatch.setattr("blueprints.admin.storage.upload_fileobj", mock_upload)

        resp = client.post(
            f"/admin/user_gdpr_export/{regular_user.id}",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "key" in uploaded

        zf = zipfile.ZipFile(io.BytesIO(uploaded["data"]))
        user_json = json.loads(zf.read("user.json"))
        assert user_json["deleted_at"] is not None

    def test_gdpr_export_requires_post(self, client, admin_user):
        login_admin(client, admin_user)
        resp = client.get(f"/admin/user_gdpr_export/{admin_user.id}")
        assert resp.status_code == 405

    def test_user_edit_shows_agb_acceptance_info(
        self, client, admin_user, regular_user
    ):
        regular_user.agb_version = "1.0"
        regular_user.agb_accepted_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db.session.commit()

        login_admin(client, admin_user)
        response = client.get(f"/admin/user_edit/{regular_user.id}")
        html = response.data.decode()
        assert "1.0" in html
        assert "2026-01-01" in html


# ---------------------------------------------------------------------------
# Notify AGB
# ---------------------------------------------------------------------------


class TestNotifyAgb:
    def test_notify_agb_requires_login(self, client):
        response = client.get("/admin/notify_agb", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location

    def test_notify_agb_requires_admin_role(self, client, regular_user):
        login_regular(client, regular_user)
        response = client.get("/admin/notify_agb", follow_redirects=True)
        html = html_text(response)
        assert "Access denied." in html

    def test_notify_agb_get_shows_form(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.get("/admin/notify_agb")
        assert response.status_code == 200
        html = response.data.decode()
        assert "agb_version" in html
        assert "effective_date" in html

    def test_notify_agb_post_creates_agb_update_record(self, client, admin_user):
        login_admin(client, admin_user)
        effective = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
        with patch("blueprints.admin.notify_agb_change"):
            response = client.post(
                "/admin/notify_agb",
                data={
                    "agb_version": "2.0",
                    "summary": "Updated data processing terms.",
                    "effective_date": effective,
                },
                follow_redirects=True,
            )
        assert response.status_code == 200
        html = html_text(response)
        assert "Benachrichtigung" in html

        update = db.session.execute(
            select(AgbUpdate).where(AgbUpdate.version == "2.0")
        ).scalar_one_or_none()
        assert update is not None
        assert update.applied_at is None
        assert update.summary == "Updated data processing terms."

    def test_notify_agb_post_missing_fields_shows_error(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.post(
            "/admin/notify_agb",
            data={"agb_version": "2.0"},
            follow_redirects=True,
        )
        html = html_text(response)
        assert "angeben" in html

    def test_notify_agb_post_sends_emails_to_active_users(
        self, client, admin_user, regular_user
    ):
        login_admin(client, admin_user)
        effective = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
        with patch("blueprints.admin.notify_agb_change") as mock_mail:
            client.post(
                "/admin/notify_agb",
                data={
                    "agb_version": "2.0",
                    "summary": "Test change.",
                    "effective_date": effective,
                },
                follow_redirects=True,
            )
        assert mock_mail.called
        called_emails = {call.args[0] for call in mock_mail.call_args_list}
        assert regular_user.email in called_emails

    def test_notify_agb_get_shows_existing_updates(self, client, admin_user):
        agb_update = AgbUpdate(
            version="1.5",
            summary="Minor wording change.",
            effective_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.session.add(agb_update)
        db.session.commit()

        login_admin(client, admin_user)
        response = client.get("/admin/notify_agb")
        html = response.data.decode()
        assert "1.5" in html


# ---------------------------------------------------------------------------
# User create sets AGB fields
# ---------------------------------------------------------------------------


class TestUserCreateAgbFields:
    def test_admin_created_user_has_agb_fields_set(self, client, admin_user):
        login_admin(client, admin_user)
        client.post(
            "/admin/user_create",
            data={
                "email": "agbtest@test.com",
                "password": "AgbTestPass1!",
                "active": "on",
            },
            follow_redirects=True,
        )
        user = db.session.execute(
            select(User).where(User.email == "agbtest@test.com")
        ).scalar_one_or_none()
        assert user is not None
        assert user.agb_accepted_at is not None
        assert user.agb_version is not None


# ---------------------------------------------------------------------------
# System page
# ---------------------------------------------------------------------------


def _remote_response(commit):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.json.return_value = {"commit": commit, "version": "v1", "built_at": "t"}
    return resp


class TestAdminSystem:
    @pytest.fixture(autouse=True)
    def _no_network(self):
        from unittest.mock import patch

        with patch("services.system.storage._client"), patch(
            "services.system.requests.get", side_effect=OSError("down")
        ) as get:
            self.http_get = get
            yield

    def test_system_requires_login(self, client):
        response = client.get("/admin/system", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location

    def test_system_requires_admin_role(self, client, regular_user):
        login_regular(client, regular_user)
        response = client.get("/admin/system", follow_redirects=True)
        assert response.status_code == 200
        assert "Access denied." in html_text(response)

    def test_system_accessible_to_admin(self, client, admin_user):
        login_admin(client, admin_user)
        assert client.get("/admin/system").status_code == 200

    def test_system_renders_checks_and_builds(self, client, admin_user):
        import platform
        from unittest.mock import patch

        login_admin(client, admin_user)
        with patch("services.system.storage._client") as s3, patch(
            "services.system.requests.get", side_effect=OSError("down")
        ):
            s3.head_bucket.return_value = {}
            html = html_text(client.get("/admin/system"))
        assert "PostgreSQL" in html
        assert "Redis" in html
        assert "Object storage" in html
        assert " ms" in html
        assert platform.python_version() in html
        assert "Gunicorn" in html
        assert "Backend" in html
        assert "Frontend" in html
        assert "unreachable" in html

    def test_system_handles_failing_dependency(self, client, admin_user):
        from unittest.mock import patch

        login_admin(client, admin_user)
        with patch("services.system.storage._client") as s3, patch(
            "services.system.requests.get", side_effect=OSError("down")
        ):
            s3.head_bucket.side_effect = RuntimeError("bucket gone")
            response = client.get("/admin/system")
        assert response.status_code == 200
        html = html_text(response)
        assert "A dependency is failing" in html
        assert "bucket gone" in html

    def test_system_handles_failing_database(self, client, admin_user):
        from unittest.mock import patch

        login_admin(client, admin_user)
        real_execute = db.session.execute

        def fail_select_one(stmt, *a, **kw):
            if str(stmt) == "SELECT 1":
                raise RuntimeError("db gone")
            return real_execute(stmt, *a, **kw)

        with patch("services.system.storage._client"), patch(
            "services.system.requests.get", side_effect=OSError("down")
        ), patch.object(db.session, "execute", side_effect=fail_select_one):
            response = client.get("/admin/system")
        assert response.status_code == 200
        assert "A dependency is failing" in html_text(response)

    def test_system_unreachable_component_warns(self, client, admin_user):
        from unittest.mock import patch

        login_admin(client, admin_user)
        with patch("services.system.storage._client"), patch(
            "services.system.requests.get", side_effect=OSError("down")
        ):
            html = html_text(client.get("/admin/system"))
        assert "A component is unreachable" in html

    def test_system_detects_commit_mismatch(self, client, admin_user):
        from unittest.mock import patch

        login_admin(client, admin_user)
        with patch("services.system.storage._client"), patch(
            "services.system.requests.get", return_value=_remote_response("other")
        ):
            html = html_text(client.get("/admin/system"))
        assert "not on the same commit" in html

    def test_system_matching_commits_show_no_warning(self, client, admin_user):
        from unittest.mock import patch
        from config import GIT_HASH

        login_admin(client, admin_user)
        with patch("services.system.storage._client"), patch(
            "services.system.requests.get", return_value=_remote_response(GIT_HASH)
        ):
            html = html_text(client.get("/admin/system"))
        assert "not on the same commit" not in html

    def test_system_flags_overdue_job(self, client, admin_user):
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        from models import db, JobRun

        db.session.add(
            JobRun(
                job_name="purge-audit-logs",
                ran_at=datetime.now(timezone.utc) - timedelta(hours=40),
                status="success",
            )
        )
        db.session.add(
            JobRun(
                job_name="purge-deleted-accounts",
                ran_at=datetime.now(timezone.utc) - timedelta(hours=1),
                status="success",
            )
        )
        db.session.commit()
        login_admin(client, admin_user)
        with patch("services.system.storage._client"), patch(
            "services.system.requests.get", side_effect=OSError("down")
        ):
            html = html_text(client.get("/admin/system"))
        assert html.count(">overdue<") == 1
        assert "on time" in html

    def test_system_flags_failed_job(self, client, admin_user):
        from datetime import datetime, timezone
        from unittest.mock import patch
        from models import db, JobRun

        db.session.add(
            JobRun(
                job_name="purge-audit-logs",
                ran_at=datetime.now(timezone.utc),
                status="failed",
                error_message="boom",
            )
        )
        db.session.commit()
        login_admin(client, admin_user)
        with patch("services.system.storage._client"), patch(
            "services.system.requests.get", side_effect=OSError("down")
        ):
            html = html_text(client.get("/admin/system"))
        assert ">failed<" in html
        assert "boom" in html

    def test_dashboard_status_card(self, client, admin_user):
        from config import GIT_HASH

        login_admin(client, admin_user)
        response = client.get("/")
        self.http_get.assert_not_called()
        html = response.get_data(as_text=True)
        assert 'id="system-status-card"' in html
        assert "status-dot" in html
        assert GIT_HASH[:8] in html
        assert "/admin/system" in html

    def test_footer_shows_version_and_commit(self, client, admin_user):
        from unittest.mock import patch
        from config import APP_VERSION, GIT_HASH

        login_admin(client, admin_user)
        with patch("services.system.storage._client"), patch(
            "services.system.requests.get", side_effect=OSError("down")
        ):
            html = html_text(client.get("/admin/system"))
        assert f"{APP_VERSION} · {GIT_HASH[:8]}" in html


# ---------------------------------------------------------------------------
# POST /admin/user_activate/<id>, /admin/user_resend_activation/<id>
# ---------------------------------------------------------------------------


@pytest.fixture
def pending_user():
    user = User(
        email="pending@test.com",
        active=False,
        activation_pending=True,
        activation_token="old-token",
        activation_token_created_at=datetime.now(timezone.utc),
    )
    user.set_password("PendingPass123!")
    db.session.add(user)
    db.session.commit()
    return user


def _beta_slots_used():
    return db.session.scalar(
        select(func.count(User.id)).where(
            db.or_(User.active.is_(True), User.activation_pending.is_(True)),
            User.deleted_at.is_(None),
        )
    )


def _audit_entries(audit_type):
    return (
        db.session.execute(select(AuditLog).where(AuditLog.audit_type == audit_type))
        .scalars()
        .all()
    )


class TestAdminUserActivate:
    def test_requires_login(self, client, pending_user):
        response = client.post(f"/admin/user_activate/{pending_user.id}")
        assert response.status_code == 302
        assert "/login" in response.location

    def test_requires_admin_role(self, client, regular_user, pending_user):
        login_regular(client, regular_user)
        response = client.post(
            f"/admin/user_activate/{pending_user.id}", follow_redirects=True
        )
        assert "Access denied." in html_text(response)
        assert db.session.get(User, pending_user.id).activation_pending is True

    def test_requires_post(self, client, admin_user, pending_user):
        login_admin(client, admin_user)
        assert client.get(f"/admin/user_activate/{pending_user.id}").status_code == 405

    def test_success(self, client, admin_user, pending_user):
        login_admin(client, admin_user)
        response = client.post(
            f"/admin/user_activate/{pending_user.id}", follow_redirects=True
        )
        assert "activated!" in response.data.decode()
        user = db.session.get(User, pending_user.id)
        assert user.active is True
        assert user.activation_pending is False
        assert user.activation_token is None
        (entry,) = _audit_entries(AuditLogType.user_activated)
        assert entry.creator_id == admin_user.id
        assert entry.related_object_id == str(pending_user.id)

    def test_activated_user_can_log_in(self, client, admin_user, pending_user):
        login_admin(client, admin_user)
        client.post(f"/admin/user_activate/{pending_user.id}")
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "pending@test.com", "password": "PendingPass123!"},
        )
        assert res.status_code == 200

    def test_already_active_rejected(self, client, admin_user, regular_user):
        login_admin(client, admin_user)
        response = client.post(
            f"/admin/user_activate/{regular_user.id}", follow_redirects=True
        )
        assert "not pending activation" in response.data.decode()
        assert _audit_entries(AuditLogType.user_activated) == []

    def test_system_user_rejected(self, client, admin_user):
        system = User(
            email="system@test.com",
            active=False,
            activation_pending=True,
            activation_token="sys-token",
            is_system=True,
        )
        db.session.add(system)
        db.session.commit()
        login_admin(client, admin_user)
        response = client.post(
            f"/admin/user_activate/{system.id}", follow_redirects=True
        )
        assert "System users cannot be activated." in response.data.decode()
        assert db.session.get(User, system.id).activation_pending is True

    def test_unknown_user_shows_error(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.post("/admin/user_activate/99999", follow_redirects=True)
        assert "unknown" in response.data.decode()

    def test_via_edit_form(self, client, admin_user, pending_user):
        login_admin(client, admin_user)
        client.post(
            f"/admin/user_edit/{pending_user.id}",
            data={"active": "on", "subscription": "free"},
        )
        user = db.session.get(User, pending_user.id)
        assert user.active is True
        assert user.activation_pending is False
        assert user.activation_token is None
        (entry,) = _audit_entries(AuditLogType.user_activated)
        assert entry.creator_id == admin_user.id
        assert _audit_entries(AuditLogType.user_reactivated) == []

    def test_beta_slots_unchanged(self, client, admin_user, pending_user):
        login_admin(client, admin_user)
        before = _beta_slots_used()
        client.post(f"/admin/user_activate/{pending_user.id}")
        assert _beta_slots_used() == before

    def test_token_never_shown(self, client, admin_user, pending_user):
        login_admin(client, admin_user)
        for url in ("/admin/users", f"/admin/user_edit/{pending_user.id}"):
            html = client.get(url).data.decode()
            assert "old-token" not in html
            assert f"/admin/user_activate/{pending_user.id}" in html
            assert f"/admin/user_resend_activation/{pending_user.id}" in html


class TestAdminUserResendActivation:
    def test_requires_login(self, client, pending_user):
        response = client.post(f"/admin/user_resend_activation/{pending_user.id}")
        assert response.status_code == 302
        assert "/login" in response.location

    def test_requires_admin_role(self, client, regular_user, pending_user):
        login_regular(client, regular_user)
        with patch("blueprints.admin.notify_activation_email") as mock_mail:
            response = client.post(
                f"/admin/user_resend_activation/{pending_user.id}",
                follow_redirects=True,
            )
        assert "Access denied." in html_text(response)
        mock_mail.assert_not_called()

    def test_requires_post(self, client, admin_user, pending_user):
        login_admin(client, admin_user)
        response = client.get(f"/admin/user_resend_activation/{pending_user.id}")
        assert response.status_code == 405

    def test_success(self, client, admin_user, pending_user):
        login_admin(client, admin_user)
        with patch("blueprints.admin.notify_activation_email") as mock_mail:
            client.post(f"/admin/user_resend_activation/{pending_user.id}")
        user = db.session.get(User, pending_user.id)
        assert user.activation_token not in (None, "old-token")
        assert user.activation_pending is True
        mock_mail.assert_called_once()
        assert mock_mail.call_args.args[0] == "pending@test.com"
        assert user.activation_token in mock_mail.call_args.args[1]
        (entry,) = _audit_entries(AuditLogType.activation_token_resent)
        assert entry.creator_id == admin_user.id

    def test_old_token_stops_working(self, client, admin_user, pending_user):
        login_admin(client, admin_user)
        with patch("blueprints.admin.notify_activation_email"):
            client.post(f"/admin/user_resend_activation/{pending_user.id}")
        res = client.post("/api/v1/auth/activate", json={"token": "old-token"})
        assert res.status_code != 200

    def test_already_active_rejected(self, client, admin_user, regular_user):
        login_admin(client, admin_user)
        with patch("blueprints.admin.notify_activation_email") as mock_mail:
            response = client.post(
                f"/admin/user_resend_activation/{regular_user.id}",
                follow_redirects=True,
            )
        assert "not pending activation" in response.data.decode()
        mock_mail.assert_not_called()

    def test_system_user_rejected(self, client, admin_user):
        system = User(
            email="system@test.com",
            active=False,
            activation_pending=True,
            activation_token="sys-token",
            is_system=True,
        )
        db.session.add(system)
        db.session.commit()
        login_admin(client, admin_user)
        with patch("blueprints.admin.notify_activation_email") as mock_mail:
            client.post(f"/admin/user_resend_activation/{system.id}")
        mock_mail.assert_not_called()
        assert db.session.get(User, system.id).activation_token == "sys-token"

    def test_beta_slots_unchanged(self, client, admin_user, pending_user):
        login_admin(client, admin_user)
        before = _beta_slots_used()
        with patch("blueprints.admin.notify_activation_email"):
            client.post(f"/admin/user_resend_activation/{pending_user.id}")
        assert _beta_slots_used() == before


# ---------------------------------------------------------------------------
# GET /admin/workers, POST /admin/workers/jobs/<id>/retry|discard
# ---------------------------------------------------------------------------

VIDEO_UUID = "22222222-2222-2222-2222-222222222222"


def _add_job(queue="video", task="process_video", status="todo", attempts=0, video_uuid=VIDEO_UUID):
    """Insert a job; the status goes through UPDATE so the queue's triggers write the events."""
    from sqlalchemy import text

    job_id = db.session.execute(
        text(
            "INSERT INTO procrastinate_jobs (queue_name, task_name, args, attempts) "
            "VALUES (:q, :t, CAST(:a AS jsonb), :n) RETURNING id"
        ),
        {"q": queue, "t": task, "a": json.dumps({"video_uuid": video_uuid}), "n": attempts},
    ).scalar_one()
    if status == "doing":
        db.session.execute(
            text("UPDATE procrastinate_jobs SET status = 'doing' WHERE id = :id"), {"id": job_id}
        )
    elif status in ("failed", "succeeded"):
        db.session.execute(
            text("UPDATE procrastinate_jobs SET status = 'doing' WHERE id = :id"), {"id": job_id}
        )
        db.session.execute(
            text("UPDATE procrastinate_jobs SET status = CAST(:s AS procrastinate_job_status) WHERE id = :id"),
            {"s": status, "id": job_id},
        )
    db.session.commit()
    return job_id


def _job_status(job_id):
    from sqlalchemy import text

    return db.session.execute(
        text("SELECT status::text FROM procrastinate_jobs WHERE id = :id"), {"id": job_id}
    ).scalar_one_or_none()


def _beat(queue, seconds_ago, hostname=None):
    from models import WorkerHeartbeat

    db.session.add(
        WorkerHeartbeat(
            hostname=hostname or f"worker-{queue}-0",
            queue_name=queue,
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=seconds_ago),
        )
    )
    db.session.commit()


def _failed_video():
    from models import Library, Video, VideoProcessingStatus

    user = User(email="photo@test.com", active=True)
    db.session.add(user)
    db.session.commit()
    lib = Library(user_id=user.id, name="Lib")
    db.session.add(lib)
    db.session.commit()
    video = Video(
        uuid=VIDEO_UUID,
        library_id=lib.id,
        s3_key=f"{VIDEO_UUID}.mp4",
        original_filename="clip.mp4",
        content_type="video/mp4",
        size=1000,
        processing_status=VideoProcessingStatus.failed,
    )
    db.session.add(video)
    db.session.commit()
    return video


class TestAdminWorkers:
    def test_workers_requires_login(self, client):
        response = client.get("/admin/workers", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.location

    def test_workers_requires_admin_role(self, client, regular_user):
        login_regular(client, regular_user)
        response = client.get("/admin/workers", follow_redirects=True)
        assert response.status_code == 200
        assert "Access denied." in html_text(response)

    def test_workers_accessible_to_admin(self, client, admin_user):
        login_admin(client, admin_user)
        response = client.get("/admin/workers")
        assert response.status_code == 200
        html = html_text(response)
        for queue in ("default", "video", "photo"):
            assert f'id="pipeline-{queue}"' in html
        assert "No job is running." in html
        assert "No failed jobs." in html

    def test_workers_renders_pipeline_overview(self, client, admin_user):
        from sqlalchemy import text

        _add_job(status="todo")
        queued = _add_job(status="todo", video_uuid="q2")
        db.session.execute(
            text(
                "UPDATE procrastinate_events SET at = now() - interval '5 minutes' "
                "WHERE job_id = :id"
            ),
            {"id": queued},
        )
        _add_job(status="failed")
        _add_job(status="succeeded")
        _beat("video", 4)
        _beat("default", 120)
        login_admin(client, admin_user)

        html = html_text(client.get("/admin/workers"))

        video_row = html.split('id="pipeline-video"')[1].split("</tr>")[0]
        assert "1 alive" in video_row
        assert "last heartbeat 4 s ago" in video_row
        assert "badge-error\">1</span>" in video_row  # failed
        assert "5 min" in video_row  # oldest queued
        default_row = html.split('id="pipeline-default"')[1].split("</tr>")[0]
        assert "0 alive" in default_row
        assert "2 min ago" in default_row
        photo_row = html.split('id="pipeline-photo"')[1].split("</tr>")[0]
        assert "none seen" in photo_row
        assert "—" in photo_row

    def test_workers_renders_running_jobs_with_current_step(self, client, admin_user):
        from services.videos import clear_video_step, set_video_step

        job_id = _add_job(status="doing")
        set_video_step(VIDEO_UUID, "Probing & thumbnail")
        login_admin(client, admin_user)
        try:
            html = html_text(client.get("/admin/workers"))
        finally:
            clear_video_step(VIDEO_UUID)

        row = html.split('id="running-jobs-table"')[1].split("</tr>", 2)[1]
        assert f"<td>{job_id}</td>" in row
        assert "process_video" in row
        assert VIDEO_UUID in row
        assert "UTC" in row
        assert "Probing & thumbnail" in row

    def test_workers_renders_failed_jobs(self, client, admin_user):
        from models import WorkerJobError

        job_id = _add_job(status="failed", attempts=2)
        db.session.add(
            WorkerJobError(
                job_id=job_id,
                queue_name="video",
                task_name="process_video",
                error_message="ValueError: Could not extract video frame",
            )
        )
        db.session.commit()
        login_admin(client, admin_user)

        html = html_text(client.get("/admin/workers"))

        row = html.split('id="failed-jobs-table"')[1].split("</tr>", 2)[1]
        assert f"<td>{job_id}</td>" in row
        assert VIDEO_UUID in row
        assert "<td>3</td>" in row  # runs: first run plus two retries
        assert "ValueError: Could not extract video frame" in row
        assert f"/admin/workers/jobs/{job_id}/retry" in row
        assert f"/admin/workers/jobs/{job_id}/discard" in row

    def test_workers_page_shows_no_payload_beyond_ids(self, client, admin_user):
        from sqlalchemy import text

        job_id = _add_job(status="failed")
        db.session.execute(
            text("UPDATE procrastinate_jobs SET args = CAST(:a AS jsonb) WHERE id = :id"),
            {"a": json.dumps({"video_uuid": VIDEO_UUID, "secret": "hunter2"}), "id": job_id},
        )
        db.session.commit()
        login_admin(client, admin_user)
        assert "hunter2" not in html_text(client.get("/admin/workers"))

    def test_worker_job_retry_action(self, client, admin_user):
        from models import VideoProcessingStatus, WorkerJobError

        video = _failed_video()
        job_id = _add_job(status="failed")
        db.session.add(
            WorkerJobError(
                job_id=job_id, queue_name="video", task_name="process_video", error_message="x"
            )
        )
        db.session.commit()
        login_admin(client, admin_user)

        response = client.post(f"/admin/workers/jobs/{job_id}/retry", follow_redirects=False)

        assert response.status_code == 302
        assert response.location.endswith("/admin/workers")
        assert _job_status(job_id) == "todo"
        db.session.refresh(video)
        assert video.processing_status == VideoProcessingStatus.processing
        assert db.session.get(WorkerJobError, job_id) is None
        (entry,) = _audit_entries(AuditLogType.worker_job_retried)
        assert entry.creator_id == admin_user.id
        assert entry.related_object_type == "worker_job"
        assert entry.related_object_id == str(job_id)

    def test_worker_job_discard_action(self, client, admin_user):
        from sqlalchemy import text

        job_id = _add_job(status="failed")
        assert db.session.execute(
            text("SELECT count(*) FROM procrastinate_events WHERE job_id = :id"), {"id": job_id}
        ).scalar_one()
        login_admin(client, admin_user)

        response = client.post(f"/admin/workers/jobs/{job_id}/discard", follow_redirects=False)

        assert response.status_code == 302
        assert _job_status(job_id) is None
        assert db.session.execute(
            text("SELECT count(*) FROM procrastinate_events WHERE job_id = :id"), {"id": job_id}
        ).scalar_one() == 0
        (entry,) = _audit_entries(AuditLogType.worker_job_discarded)
        assert entry.creator_id == admin_user.id
        assert entry.related_object_id == str(job_id)

    @pytest.mark.parametrize("action", ["retry", "discard"])
    def test_worker_job_action_ignores_jobs_that_are_not_failed(self, client, admin_user, action):
        job_id = _add_job(status="todo")
        login_admin(client, admin_user)

        response = client.post(f"/admin/workers/jobs/{job_id}/{action}", follow_redirects=True)

        assert "is not a failed job" in html_text(response)
        assert _job_status(job_id) == "todo"
        assert _audit_entries(AuditLogType.worker_job_retried) == []
        assert _audit_entries(AuditLogType.worker_job_discarded) == []

    @pytest.mark.parametrize("action", ["retry", "discard"])
    def test_worker_job_actions_require_login(self, client, action):
        job_id = _add_job(status="failed")
        response = client.post(f"/admin/workers/jobs/{job_id}/{action}")
        assert response.status_code == 302
        assert "/login" in response.location
        assert _job_status(job_id) == "failed"

    @pytest.mark.parametrize("action", ["retry", "discard"])
    def test_worker_job_actions_require_admin(self, client, regular_user, action):
        job_id = _add_job(status="failed")
        login_regular(client, regular_user)

        response = client.post(f"/admin/workers/jobs/{job_id}/{action}", follow_redirects=True)

        assert "Access denied." in html_text(response)
        assert _job_status(job_id) == "failed"
        assert _audit_entries(AuditLogType.worker_job_retried) == []
        assert _audit_entries(AuditLogType.worker_job_discarded) == []

    def test_dashboard_renders_worker_status_card(self, client, admin_user):
        _add_job(status="failed")
        _add_job(status="doing", video_uuid="b")
        _add_job(status="todo", video_uuid="c")
        _beat("default", 1)
        _beat("video", 1)
        login_admin(client, admin_user)

        html = html_text(client.get("/"))

        card = html.split('id="worker-status-card"')[1].split("</div>\n</div>")[0]
        assert "status-dot-warning" in card
        assert "Failed jobs need attention" in card
        assert "1 running" in card and "1 queued" in card and "1 failed" in card
        assert 'href="/admin/workers"' in card

    def test_dashboard_card_is_red_without_live_workers(self, client, admin_user):
        login_admin(client, admin_user)
        html = html_text(client.get("/"))
        card = html.split('id="worker-status-card"')[1].split("</div>\n</div>")[0]
        assert "status-dot-error" in card
        assert "No worker is alive for default" in card

    def test_nav_links_to_workers(self, client, admin_user):
        login_admin(client, admin_user)
        assert 'href="/admin/workers"' in html_text(client.get("/admin/system"))
