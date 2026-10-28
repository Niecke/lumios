"""Tests for the photographer video routes: /api/v1/libraries/<id>/videos/*

Coverage targets:
  POST   /api/v1/libraries/<id>/videos/init                   presigned upload
  POST   /api/v1/libraries/<id>/videos/<uuid>/finalize        confirm upload, enqueue
  GET    /api/v1/libraries/<id>/videos/<uuid>                 metadata / status
  DELETE /api/v1/libraries/<id>/videos/<video_id>             soft-delete
  - feature gate (VIDEO_UPLOADS_ENABLED), auth, role, library scoping, validation
  - quota boundaries of the init route
"""

from datetime import datetime, timezone
from unittest.mock import PropertyMock, patch

import pytest
from sqlalchemy import select

from models import (
    db,
    User,
    Role,
    Library,
    Image,
    Video,
    VideoProcessingStatus,
    AuditLog,
    AuditLogType,
)
from services.token import create_token

SIZE = 5000


@pytest.fixture
def photographer():
    # The photographer role is seeded by a migration; reuse it.
    role = db.session.execute(
        select(Role).where(Role.name == "photographer")
    ).scalar_one_or_none()
    if role is None:
        role = Role(name="photographer", description="Photographer")
        db.session.add(role)
    user = User(email="photo@test.com", active=True)
    user.set_password("PhotoPass123!")
    user.roles.append(role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def library(photographer):
    lib = Library(user_id=photographer.id, name="Video Library")
    db.session.add(lib)
    db.session.commit()
    return lib


@pytest.fixture(autouse=True)
def video_enabled():
    with patch("blueprints.api.videos.VIDEO_UPLOADS_ENABLED", True), patch(
        "services.videos.storage"
    ) as st:
        st.create_presigned_put_url.return_value = "http://example.com/put"
        yield


def _limits(storage=None, media=5000):
    return {
        "max_libraries": 10,
        "max_images_per_library": media,
        "max_storage_bytes": storage if storage is not None else 10**9,
    }


def _patch_limits(**kwargs):
    return patch.object(
        User, "effective_limits", new_callable=PropertyMock, return_value=_limits(**kwargs)
    )


def _add_media(library, count, size=1000):
    for i in range(count):
        db.session.add(
            Image(
                library_id=library.id,
                s3_key=f"v-{i}.jpg",
                original_filename=f"v-{i}.jpg",
                content_type="image/jpeg",
                size=size,
            )
        )
    db.session.commit()


def _post(client, user, library):
    token = create_token(user.id, user.email, [r.name for r in user.roles])
    return client.post(
        f"/api/v1/libraries/{library.id}/videos/init",
        json={"filename": "v.mp4", "content_type": "video/mp4", "size": SIZE},
        headers={"Authorization": f"Bearer {token}"},
    )


class TestVideoInitQuotas:
    def test_media_count_below_limit_allowed(self, client, photographer, library):
        _add_media(library, 2)
        with _patch_limits(media=3):
            assert _post(client, photographer, library).status_code == 201

    def test_media_count_at_limit_rejected(self, client, photographer, library):
        _add_media(library, 3)
        with _patch_limits(media=3):
            assert _post(client, photographer, library).status_code == 422

    def test_storage_exactly_at_limit_allowed(self, client, photographer, library):
        _add_media(library, 1)
        with _patch_limits(storage=1000 + SIZE):
            assert _post(client, photographer, library).status_code == 201

    def test_storage_one_byte_over_rejected(self, client, photographer, library):
        _add_media(library, 1)
        with _patch_limits(storage=1000 + SIZE - 1):
            assert _post(client, photographer, library).status_code == 422

    def test_storage_overshoot_rejected(self, client, photographer, library):
        _add_media(library, 1)
        with _patch_limits(storage=1000 + SIZE // 2):
            res = _post(client, photographer, library)
        assert res.status_code == 422
        assert res.get_json()["error"].endswith("for your subscription.")


# ---------------------------------------------------------------------------
# Shared helpers for the route tests below
# ---------------------------------------------------------------------------

VIDEO_UUID = "11111111-1111-1111-1111-111111111111"


def _headers(user):
    token = create_token(user.id, user.email, [r.name for r in user.roles])
    return {"Authorization": f"Bearer {token}"}


def _make_video(library, status=VideoProcessingStatus.uploading, uuid=VIDEO_UUID):
    video = Video(
        uuid=uuid,
        library_id=library.id,
        s3_key=f"{uuid}.mp4",
        original_filename="clip.mp4",
        content_type="video/mp4",
        size=1000,
        processing_status=status,
    )
    db.session.add(video)
    db.session.commit()
    return video


@pytest.fixture
def other_user():
    role = db.session.execute(
        select(Role).where(Role.name == "photographer")
    ).scalar_one()
    user = User(email="other@test.com", active=True)
    user.set_password("OtherPass123!")
    user.roles.append(role)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def other_library(other_user):
    lib = Library(user_id=other_user.id, name="Other Library")
    db.session.add(lib)
    db.session.commit()
    return lib


def _audit_types():
    return [
        row.audit_type
        for row in db.session.execute(select(AuditLog)).scalars().all()
    ]


def _init(client, user, library_id, **payload):
    body = {"filename": "v.mp4", "content_type": "video/mp4", "size": SIZE}
    body.update(payload)
    body = {k: v for k, v in body.items() if v is not None}
    return client.post(
        f"/api/v1/libraries/{library_id}/videos/init",
        json=body,
        headers=_headers(user) if user else {},
    )


def _finalize(client, user, library_id, video_uuid=VIDEO_UUID):
    return client.post(
        f"/api/v1/libraries/{library_id}/videos/{video_uuid}/finalize",
        headers=_headers(user) if user else {},
    )


def _get(client, user, library_id, video_uuid=VIDEO_UUID):
    return client.get(
        f"/api/v1/libraries/{library_id}/videos/{video_uuid}",
        headers=_headers(user) if user else {},
    )


def _delete(client, user, library_id, video_id):
    return client.delete(
        f"/api/v1/libraries/{library_id}/videos/{video_id}",
        headers=_headers(user) if user else {},
    )


# ---------------------------------------------------------------------------
# Feature gate
# ---------------------------------------------------------------------------


class TestVideoFeatureGate:
    @pytest.fixture(autouse=True)
    def gate_closed(self):
        with patch("blueprints.api.videos.VIDEO_UPLOADS_ENABLED", False):
            yield

    def test_init_returns_501(self, client, photographer, library):
        assert _init(client, photographer, library.id).status_code == 501

    def test_finalize_returns_501(self, client, photographer, library):
        assert _finalize(client, photographer, library.id).status_code == 501

    def test_get_returns_501(self, client, photographer, library):
        assert _get(client, photographer, library.id).status_code == 501

    def test_delete_returns_501(self, client, photographer, library):
        assert _delete(client, photographer, library.id, 1).status_code == 501


# ---------------------------------------------------------------------------
# Auth and role enforcement (same for all four routes)
# ---------------------------------------------------------------------------


class TestVideoAuth:
    @pytest.fixture
    def non_photographer(self, regular_user):
        return regular_user

    def _calls(self, client, user, library_id):
        return [
            _init(client, user, library_id),
            _finalize(client, user, library_id),
            _get(client, user, library_id),
            _delete(client, user, library_id, 1),
        ]

    def test_unauthenticated_returns_401(self, client, library):
        for res in self._calls(client, None, library.id):
            assert res.status_code == 401

    def test_non_photographer_returns_403(self, client, non_photographer, library):
        for res in self._calls(client, non_photographer, library.id):
            assert res.status_code == 403


# ---------------------------------------------------------------------------
# POST .../videos/init
# ---------------------------------------------------------------------------


class TestVideoInit:
    def test_nonexistent_library_returns_404(self, client, photographer):
        assert _init(client, photographer, 99999).status_code == 404

    def test_foreign_library_returns_404(self, client, photographer, other_library):
        assert _init(client, photographer, other_library.id).status_code == 404

    def test_soft_deleted_library_returns_404(self, client, photographer, library):
        library.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        assert _init(client, photographer, library.id).status_code == 404

    def test_missing_size_returns_400(self, client, photographer, library):
        assert _init(client, photographer, library.id, size=None).status_code == 400

    @pytest.mark.parametrize("size", [0, -5, "100", 1.5])
    def test_invalid_size_returns_400(self, client, photographer, library, size):
        assert _init(client, photographer, library.id, size=size).status_code == 400

    def test_missing_filename_returns_422(self, client, photographer, library):
        res = _init(client, photographer, library.id, filename="  ")
        assert res.status_code == 422
        assert res.get_json()["error"] == "Filename is required"

    @pytest.mark.parametrize("content_type", ["image/jpeg", "video/avi", ""])
    def test_unsupported_content_type_returns_422(
        self, client, photographer, library, content_type
    ):
        res = _init(client, photographer, library.id, content_type=content_type)
        assert res.status_code == 422

    def test_oversize_returns_422(self, client, photographer, library):
        with patch("services.videos.MAX_VIDEO_FILE_SIZE", 1000):
            res = _init(client, photographer, library.id, size=1001)
        assert res.status_code == 422
        assert res.get_json()["error"].startswith("File too large")

    def test_invalid_requests_create_no_video(self, client, photographer, library):
        _init(client, photographer, library.id, content_type="image/jpeg")
        assert db.session.execute(select(Video)).scalars().all() == []

    def test_storage_failure_returns_502(self, client, photographer, library):
        with patch("services.videos.storage") as st:
            st.create_presigned_put_url.side_effect = RuntimeError("s3 down")
            res = _init(client, photographer, library.id)
        assert res.status_code == 502
        assert db.session.execute(select(Video)).scalars().all() == []

    def test_success_creates_video_and_audit_log(self, client, photographer, library):
        res = _init(client, photographer, library.id)

        assert res.status_code == 201
        body = res.get_json()
        assert set(body) == {"uuid", "upload_url"}
        assert body["upload_url"] == "http://example.com/put"

        video = db.session.execute(select(Video)).scalar_one()
        assert video.uuid == body["uuid"]
        assert video.library_id == library.id
        assert video.processing_status == VideoProcessingStatus.uploading
        assert video.is_external is False
        assert video.original_filename == "v.mp4"
        assert video.size == SIZE

        log = db.session.execute(select(AuditLog)).scalar_one()
        assert log.audit_type == AuditLogType.video_uploaded
        assert log.creator_id == photographer.id
        assert log.related_object_id == video.uuid


# ---------------------------------------------------------------------------
# POST .../videos/<uuid>/finalize
# ---------------------------------------------------------------------------


@pytest.fixture
def finalize_storage():
    """Object storage as seen by finalize_video_upload."""
    with patch("services.videos.storage") as st:
        st.object_exists.return_value = True
        yield st


class TestVideoFinalize:
    def test_nonexistent_library_returns_404(self, client, photographer):
        assert _finalize(client, photographer, 99999).status_code == 404

    def test_foreign_library_returns_404(self, client, photographer, other_library):
        _make_video(other_library)
        assert _finalize(client, photographer, other_library.id).status_code == 404

    def test_nonexistent_video_returns_404(self, client, photographer, library):
        assert _finalize(client, photographer, library.id).status_code == 404

    def test_video_of_other_library_returns_404(
        self, client, photographer, library, other_library
    ):
        _make_video(other_library)
        assert _finalize(client, photographer, library.id).status_code == 404

    def test_soft_deleted_video_returns_404(self, client, photographer, library):
        video = _make_video(library)
        video.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        assert _finalize(client, photographer, library.id).status_code == 404

    @pytest.mark.parametrize(
        "status", [VideoProcessingStatus.processing, VideoProcessingStatus.ready]
    )
    def test_not_uploading_returns_409(
        self, client, photographer, library, finalize_storage, status
    ):
        _make_video(library, status=status)
        assert _finalize(client, photographer, library.id).status_code == 409

    def test_missing_object_returns_422(
        self, client, photographer, library, finalize_storage
    ):
        _make_video(library)
        finalize_storage.object_exists.return_value = False

        res = _finalize(client, photographer, library.id)

        assert res.status_code == 422
        video = db.session.execute(select(Video)).scalar_one()
        assert video.processing_status == VideoProcessingStatus.uploading

    def test_storage_error_returns_502(
        self, client, photographer, library, finalize_storage
    ):
        _make_video(library)
        finalize_storage.object_exists.side_effect = RuntimeError("s3 down")
        assert _finalize(client, photographer, library.id).status_code == 502

    def test_defer_error_returns_502_and_allows_retry(
        self, client, photographer, library, finalize_storage
    ):
        import worker

        _make_video(library)
        with patch.object(
            worker.process_video_task, "configure", side_effect=RuntimeError("db down")
        ):
            res = _finalize(client, photographer, library.id)

        assert res.status_code == 502
        video = db.session.execute(select(Video)).scalar_one()
        assert video.processing_status == VideoProcessingStatus.uploading

    def test_success_sets_processing_and_enqueues(
        self, client, photographer, library, finalize_storage
    ):
        _make_video(library)

        res = _finalize(client, photographer, library.id)

        assert res.status_code == 200
        assert res.get_json() == {
            "uuid": VIDEO_UUID,
            "processing_status": "processing",
        }
        video = db.session.execute(select(Video)).scalar_one()
        assert video.processing_status == VideoProcessingStatus.processing

        from sqlalchemy import text

        jobs = db.session.execute(
            text("SELECT queue_name, task_name, args FROM procrastinate_jobs")
        ).mappings().all()
        assert len(jobs) == 1
        assert jobs[0]["queue_name"] == "video"
        assert jobs[0]["task_name"] == "process_video"
        assert jobs[0]["args"] == {"video_uuid": VIDEO_UUID}


# ---------------------------------------------------------------------------
# GET .../videos/<uuid>
# ---------------------------------------------------------------------------


class TestVideoGet:
    @pytest.fixture(autouse=True)
    def presign(self):
        with patch("blueprints.api.videos.storage") as st:
            st.get_presigned_url.side_effect = lambda key: f"http://s3/{key}"
            self.storage = st
            yield

    def test_nonexistent_library_returns_404(self, client, photographer):
        assert _get(client, photographer, 99999).status_code == 404

    def test_foreign_library_returns_404(self, client, photographer, other_library):
        _make_video(other_library)
        assert _get(client, photographer, other_library.id).status_code == 404

    def test_nonexistent_video_returns_404(self, client, photographer, library):
        assert _get(client, photographer, library.id).status_code == 404

    def test_video_of_other_library_returns_404(
        self, client, photographer, library, other_library
    ):
        _make_video(other_library)
        assert _get(client, photographer, library.id).status_code == 404

    def test_soft_deleted_video_returns_404(self, client, photographer, library):
        video = _make_video(library)
        video.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        assert _get(client, photographer, library.id).status_code == 404

    @pytest.mark.parametrize(
        "status", [VideoProcessingStatus.uploading, VideoProcessingStatus.processing]
    )
    def test_unfinished_video_has_no_urls(
        self, client, photographer, library, status
    ):
        _make_video(library, status=status)

        res = _get(client, photographer, library.id)

        assert res.status_code == 200
        body = res.get_json()
        assert body["uuid"] == VIDEO_UUID
        assert body["processing_status"] == status.value
        assert body["media_type"] == "video"
        assert body["original_url"] is None
        assert body["thumb_url"] is None
        self.storage.get_presigned_url.assert_not_called()

    def test_failed_video_has_no_urls(self, client, photographer, library):
        _make_video(library, status=VideoProcessingStatus.failed)
        body = _get(client, photographer, library.id).get_json()
        assert body["processing_status"] == "failed"
        assert body["original_url"] is None

    def test_ready_video_has_presigned_urls(self, client, photographer, library):
        video = _make_video(library, status=VideoProcessingStatus.ready)

        body = _get(client, photographer, library.id).get_json()

        assert body["processing_status"] == "ready"
        assert body["original_url"] == f"http://s3/{video.storage_path('originals')}"
        assert body["thumb_url"] == f"http://s3/{video.storage_path('thumbs')}"
        assert body["thumb_url"].endswith(".jpg")


# ---------------------------------------------------------------------------
# DELETE .../videos/<video_id>
# ---------------------------------------------------------------------------


class TestVideoDelete:
    def test_nonexistent_library_returns_404(self, client, photographer):
        assert _delete(client, photographer, 99999, 1).status_code == 404

    def test_foreign_library_returns_404(self, client, photographer, other_library):
        video = _make_video(other_library)
        res = _delete(client, photographer, other_library.id, video.id)
        assert res.status_code == 404
        assert db.session.get(Video, video.id).deleted_at is None

    def test_nonexistent_video_returns_404(self, client, photographer, library):
        assert _delete(client, photographer, library.id, 99999).status_code == 404

    def test_video_of_other_library_returns_404(
        self, client, photographer, library, other_library
    ):
        video = _make_video(other_library)
        assert _delete(client, photographer, library.id, video.id).status_code == 404
        assert db.session.get(Video, video.id).deleted_at is None

    def test_already_deleted_returns_404(self, client, photographer, library):
        video = _make_video(library)
        video.deleted_at = datetime.now(timezone.utc)
        db.session.commit()
        assert _delete(client, photographer, library.id, video.id).status_code == 404

    def test_success_soft_deletes_and_logs(self, client, photographer, library):
        video = _make_video(library)

        with patch("blueprints.api.videos.cache_delete") as cd, patch(
            "blueprints.api.videos.cache_delete_pattern"
        ) as cdp:
            res = _delete(client, photographer, library.id, video.id)

        assert res.status_code == 204
        assert res.data == b""
        assert db.session.get(Video, video.id).deleted_at is not None
        log = db.session.execute(select(AuditLog)).scalar_one()
        assert log.audit_type == AuditLogType.video_deleted
        assert log.creator_id == photographer.id
        assert log.related_object_id == VIDEO_UUID
        cdp.assert_called_once_with(f"public:library:{library.uuid}:*")
        cd.assert_called_once_with(f"user:storage:{photographer.id}")

    def test_deleted_video_is_gone_for_get(self, client, photographer, library):
        video = _make_video(library)
        _delete(client, photographer, library.id, video.id)
        assert _get(client, photographer, library.id).status_code == 404
