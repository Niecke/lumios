"""Tests for the background worker: enqueue, run, retry, dead letter, isolation, health."""

import asyncio
import io
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from PIL import Image as PilImage
from sqlalchemy import select, text

import worker
from models import db, Library, User, Video, VideoProcessingStatus
from services.videos import finalize_video_upload, process_video


VIDEO_UUID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def worker_uses_test_app(app, monkeypatch):
    """Jobs run in the test app instead of building a second one."""
    monkeypatch.setattr(worker, "_flask_app", app)


@pytest.fixture
def video():
    user = User(email="photo@test.com", active=True)
    db.session.add(user)
    db.session.commit()
    lib = Library(user_id=user.id, name="Lib")
    db.session.add(lib)
    db.session.commit()
    vid = Video(
        uuid=VIDEO_UUID,
        library_id=lib.id,
        s3_key=f"{VIDEO_UUID}.mp4",
        original_filename="clip.mp4",
        content_type="video/mp4",
        size=1000,
        processing_status=VideoProcessingStatus.uploading,
    )
    db.session.add(vid)
    db.session.commit()
    return vid


@pytest.fixture
def storage():
    with patch("services.videos.storage") as st:
        st.object_exists.return_value = True
        st.iter_object_chunks.return_value = iter([b"fake video bytes"])
        yield st


@pytest.fixture
def probe():
    info = {
        "frame": PilImage.new("RGB", (1280, 720), "blue"),
        "width": 1280,
        "height": 720,
        "duration_ms": 4000,
        "video_codec": "h264",
        "audio_codec": "aac",
        "bitrate": 1_000_000,
        "hevc_warning": False,
    }
    with patch("services.videos._extract_video_info", return_value=info) as p:
        yield p


def _jobs():
    rows = db.session.execute(
        text(
            "SELECT id, queue_name, task_name, status::text AS status, attempts, "
            "lock, queueing_lock, args, scheduled_at FROM procrastinate_jobs ORDER BY id"
        )
    ).mappings()
    return [dict(r) for r in rows]


def _run_worker(*queues):
    worker.worker_app.run_worker(queues=list(queues), wait=False, install_signal_handlers=False)
    db.session.remove()


def _make_due():
    db.session.execute(text("UPDATE procrastinate_jobs SET scheduled_at = now() WHERE status = 'todo'"))
    db.session.commit()


def _reload(video):
    """Fresh row: the worker run closes the test's session."""
    return db.session.execute(select(Video).where(Video.uuid == VIDEO_UUID)).scalar_one()


def _status(video):
    return _reload(video).processing_status


class TestEnqueue:
    def test_finalize_defers_job_on_video_queue(self, video, storage):
        finalize_video_upload(video)

        (job,) = _jobs()
        assert job["queue_name"] == "video"
        assert job["task_name"] == "process_video"
        assert job["status"] == "todo"
        assert job["args"] == {"video_uuid": video.uuid}
        assert job["lock"] == f"video-{video.uuid}"
        assert job["queueing_lock"] == f"video-{video.uuid}"
        assert _status(video) == VideoProcessingStatus.processing

    def test_finalize_twice_queues_one_job(self, video, storage):
        finalize_video_upload(video)
        finalize_video_upload(video)

        assert len(_jobs()) == 1

    def test_finalize_defer_failure_allows_retry(self, video, storage):
        from unittest.mock import patch

        import worker

        with patch.object(
            worker.process_video_task, "configure", side_effect=RuntimeError("db down")
        ):
            with pytest.raises(RuntimeError):
                finalize_video_upload(video)

        assert _status(video) == VideoProcessingStatus.uploading
        assert _jobs() == []

        finalize_video_upload(video)

        assert _status(video) == VideoProcessingStatus.processing
        assert len(_jobs()) == 1

    def test_finalize_missing_object_enqueues_nothing(self, video, storage):
        storage.object_exists.return_value = False
        with pytest.raises(ValueError):
            finalize_video_upload(video)

        assert _jobs() == []


class TestExecution:
    def test_job_processes_video_to_ready(self, video, storage, probe):
        finalize_video_upload(video)

        _run_worker("video")

        assert _jobs()[0]["status"] == "succeeded"
        video = _reload(video)
        assert video.processing_status == VideoProcessingStatus.ready
        assert (video.width, video.height, video.duration_ms) == (1280, 720, 4000)
        assert video.video_codec == "h264"
        thumb_args = storage.upload_fileobj.call_args.args
        assert thumb_args[1] == video.storage_path("thumbs")
        assert thumb_args[2] == "image/jpeg"
        thumb = PilImage.open(io.BytesIO(thumb_args[0].getvalue()))
        assert max(thumb.size) == 600

    def test_rerun_of_ready_video_does_nothing(self, video, storage, probe):
        finalize_video_upload(video)
        _run_worker("video")
        storage.reset_mock()
        probe.reset_mock()

        process_video(video.uuid)

        storage.iter_object_chunks.assert_not_called()
        storage.upload_fileobj.assert_not_called()
        probe.assert_not_called()
        assert _status(video) == VideoProcessingStatus.ready

    def test_job_survives_without_worker(self, video, storage, probe):
        """Nothing runs the job until a worker starts; it stays in the database."""
        finalize_video_upload(video)

        assert _jobs()[0]["status"] == "todo"
        assert _status(video) == VideoProcessingStatus.processing


class TestRetry:
    def test_transient_failure_is_retried_with_backoff(self, video, storage, probe):
        storage.iter_object_chunks.side_effect = OSError("storage hiccup")
        finalize_video_upload(video)

        _run_worker("video")

        (job,) = _jobs()
        assert job["status"] == "todo"
        assert job["attempts"] == 1
        assert (job["scheduled_at"] - datetime.now(timezone.utc)).total_seconds() > 3
        assert _status(video) == VideoProcessingStatus.processing

    def test_retry_succeeds_after_transient_failure(self, video, storage, probe):
        storage.iter_object_chunks.side_effect = [OSError("storage hiccup"), iter([b"x"])]
        finalize_video_upload(video)

        _run_worker("video")
        _make_due()
        _run_worker("video")

        # Procrastinate counts every finished run, the retry and the success
        assert _jobs()[0]["status"] == "succeeded"
        assert _jobs()[0]["attempts"] == 2
        assert _status(video) == VideoProcessingStatus.ready

    def test_exhausted_retries_end_in_failed_state(self, video, storage, probe):
        storage.iter_object_chunks.side_effect = OSError("storage down")
        finalize_video_upload(video)

        for run in range(worker.VIDEO_MAX_RUNS):
            assert _status(video) == VideoProcessingStatus.processing
            _run_worker("video")
            _make_due()

        (job,) = _jobs()
        assert job["status"] == "failed"
        assert job["attempts"] == worker.VIDEO_MAX_RUNS
        assert storage.iter_object_chunks.call_count == worker.VIDEO_MAX_RUNS
        assert _status(video) == VideoProcessingStatus.failed

    def test_failed_job_is_not_run_again(self, video, storage, probe):
        storage.iter_object_chunks.side_effect = OSError("storage down")
        finalize_video_upload(video)
        for _ in range(worker.VIDEO_MAX_RUNS):
            _run_worker("video")
            _make_due()
        calls = storage.iter_object_chunks.call_count

        _run_worker("video")

        assert storage.iter_object_chunks.call_count == calls


class TestPipelineIsolation:
    def test_default_worker_ignores_video_jobs(self, video, storage, probe):
        finalize_video_upload(video)

        _run_worker("default")
        assert _jobs()[0]["status"] == "todo"
        assert _status(video) == VideoProcessingStatus.processing

        _run_worker("video")
        assert _jobs()[0]["status"] == "succeeded"

    def test_known_queues(self):
        assert worker.QUEUES == ("default", "video", "photo")


class TestHealthCheck:
    def test_healthy_when_schema_is_there(self):
        assert worker.check_worker_health() == 0

    def test_unhealthy_when_queue_table_is_missing(self):
        with patch.object(worker.worker_app, "check_connection", return_value=False):
            assert worker.check_worker_health() == 1

    def test_unhealthy_when_database_is_unreachable(self):
        with patch.object(
            worker.worker_app, "check_connection", side_effect=RuntimeError("down")
        ):
            assert worker.check_worker_health() == 1


def _recover():
    async def run():
        async with worker.worker_app.open_async():
            return await worker.recover_stalled_jobs_now()

    handled = asyncio.run(run())
    db.session.remove()
    return handled


def _kill_worker_mid_job():
    """The state a SIGKILLed worker leaves behind: job in doing, no worker row."""
    db.session.execute(text("UPDATE procrastinate_jobs SET status = 'doing'"))
    db.session.commit()


class TestStalledJobs:
    def test_job_of_dead_worker_is_retried(self, video, storage, probe):
        finalize_video_upload(video)
        _kill_worker_mid_job()

        assert _recover() == 1

        (job,) = _jobs()
        assert job["status"] == "todo"
        assert job["attempts"] == 1
        _make_due()
        _run_worker("video")
        assert _status(video) == VideoProcessingStatus.ready

    def test_job_that_keeps_killing_workers_ends_failed(self, video, storage, probe):
        finalize_video_upload(video)
        for _ in range(worker.VIDEO_MAX_RUNS - 1):
            _kill_worker_mid_job()
            _recover()
            _make_due()
        _kill_worker_mid_job()

        assert _recover() == 1

        assert _jobs()[0]["status"] == "failed"
        assert _status(video) == VideoProcessingStatus.failed

    def test_nothing_stalled_nothing_done(self, video, storage):
        finalize_video_upload(video)

        assert _recover() == 0
        assert _jobs()[0]["status"] == "todo"


class TestWorkerDashboardSupport:
    def test_summarize_error_is_one_short_line_without_urls_or_paths(self):
        exc = ValueError(
            "first line\nfailed GET https://s3.example.com/bucket/photos/1/2/originals/x.mp4?sig=abc "
            "for photos/1/2/originals/x.mp4: " + "boom " * 100
        )

        text_ = worker.summarize_error(exc)

        assert "\n" not in text_
        assert text_.startswith("ValueError: failed GET <url> for <path>")
        assert "s3.example.com" not in text_ and "photos/" not in text_
        assert len(text_) <= worker.ERROR_MAX_LENGTH

    def test_failed_run_records_error_and_success_clears_it(self, video, storage, probe):
        from models import WorkerJobError

        job = type("J", (), {"id": 7, "attempts": 0})()
        context = type("C", (), {"job": job})()
        storage.iter_object_chunks.side_effect = OSError("down at https://s3.local/x")

        with pytest.raises(OSError):
            worker.process_video_task.func(context, VIDEO_UUID)

        row = db.session.get(WorkerJobError, 7)
        assert row.queue_name == "video" and row.task_name == "process_video"
        assert row.error_message == "OSError: down at <url>"

        storage.iter_object_chunks.side_effect = None
        storage.iter_object_chunks.return_value = iter([b"fake video bytes"])
        worker.process_video_task.func(context, VIDEO_UUID)
        db.session.expire_all()
        assert db.session.get(WorkerJobError, 7) is None

    def test_process_video_reports_steps_and_clears_them(self, video, storage, probe):
        from services import videos as video_service

        seen = []
        real = video_service.set_video_step
        with patch.object(
            video_service, "set_video_step", side_effect=lambda u, s: (seen.append(s), real(u, s))
        ):
            process_video(VIDEO_UUID)

        assert seen == [
            "Downloading",
            "Probing & thumbnail",
            "Uploading thumbnail",
            "Saving metadata",
        ]
        assert video_service.get_video_step(VIDEO_UUID) is None

    def test_step_is_cleared_when_processing_fails(self, video, storage, probe):
        from services import videos as video_service

        storage.upload_fileobj.side_effect = RuntimeError("nope")
        with pytest.raises(RuntimeError):
            process_video(VIDEO_UUID)
        assert video_service.get_video_step(VIDEO_UUID) is None

    def test_heartbeat_upserts_and_is_removed(self, app):
        from models import WorkerHeartbeat

        started = datetime.now(timezone.utc)
        worker.beat_heartbeat("video", "pod-a", started)
        worker.beat_heartbeat("video", "pod-a", started)
        assert len(db.session.execute(select(WorkerHeartbeat)).scalars().all()) == 1

        worker.remove_heartbeat("pod-a")
        db.session.expire_all()
        assert db.session.execute(select(WorkerHeartbeat)).scalars().all() == []

    def test_heartbeat_prunes_pods_gone_for_good(self, app):
        from datetime import timedelta

        from models import WorkerHeartbeat

        old = datetime.now(timezone.utc) - timedelta(seconds=worker.HEARTBEAT_PRUNE_SECONDS + 60)
        db.session.add(WorkerHeartbeat(hostname="old-pod", queue_name="video", last_heartbeat=old))
        db.session.commit()

        worker.beat_heartbeat("video", "new-pod", datetime.now(timezone.utc))

        db.session.expire_all()
        hosts = {h.hostname for h in db.session.execute(select(WorkerHeartbeat)).scalars()}
        assert hosts == {"new-pod"}


def _mail_jobs():
    return [j for j in _jobs() if j["task_name"] != "recover_stalled_jobs"]


@pytest.fixture
def mail_user():
    user = User(
        email="pending@test.com",
        active=False,
        activation_pending=True,
        activation_token="raw-secret-token",
    )
    db.session.add(user)
    db.session.commit()
    return user


class TestMailEnqueue:
    def test_every_notify_helper_queues_on_default(self, app):
        from services import mail

        mail.notify_registration("a@test.com")
        mail.notify_activation_email(5)
        mail.notify_resend_activation("a@test.com", "1.2.3.4")
        mail.notify_admin_new_account("a@test.com", "Google")
        mail.notify_account_cancellation("a@test.com")
        mail.notify_agb_change("a@test.com", "2.0", "text")
        mail.notify_gallery_finished("a@test.com", "Lib", "uuid", 3)
        mail.notify_new_support_ticket(1, "Help", "a@test.com")

        jobs = {j["task_name"]: j for j in _mail_jobs()}
        assert set(jobs) == {
            "send_registration_email",
            "send_activation_email",
            "resend_activation",
            "send_admin_new_account_email",
            "send_account_cancellation_email",
            "send_agb_change_email",
            "send_gallery_finished_email",
            "send_new_support_ticket_email",
        }
        assert all(j["queue_name"] == "default" for j in jobs.values())
        assert jobs["send_gallery_finished_email"]["args"] == {
            "photographer_email": "a@test.com",
            "library_name": "Lib",
            "library_uuid": "uuid",
            "liked_count": 3,
        }
        assert jobs["resend_activation"]["args"] == {"email": "a@test.com", "ip": "1.2.3.4"}

    def test_activation_job_holds_only_the_user_id(self, app, mail_user):
        from services import mail

        mail.notify_activation_email(mail_user.id)

        (job,) = _mail_jobs()
        assert job["args"] == {"user_id": mail_user.id}
        assert "raw-secret-token" not in str(job)

    def test_duplicate_activation_and_resend_jobs_collapse(self, app):
        from services import mail

        for _ in range(3):
            assert mail.notify_activation_email(5) is True
            assert mail.notify_resend_activation("a@test.com", "1.2.3.4") is True
        mail.notify_resend_activation("b@test.com", "1.2.3.4")

        names = sorted(j["task_name"] for j in _mail_jobs())
        assert names == ["resend_activation"] * 2 + ["send_activation_email"]


class TestMailExecution:
    def test_job_sends_the_mail_and_succeeds(self, app, mail_user):
        from services import mail

        mail.notify_activation_email(mail_user.id)
        with patch("services.mail._send") as send:
            _run_worker("default")

        send.assert_called_once()
        assert "raw-secret-token" in send.call_args.args[2]
        assert _mail_jobs()[0]["status"] == "succeeded"

    def test_failure_is_retried_records_error_and_ends_failed(self, app, mail_user):
        from models import WorkerJobError
        from services import mail

        mail.notify_activation_email(mail_user.id)
        with patch("services.mail._send", side_effect=mail.MailDeliveryError("Brevo answered with status 503")) as send:
            _run_worker("default")
            (job,) = _mail_jobs()
            assert job["status"] == "todo" and job["attempts"] == 1
            assert (job["scheduled_at"] - datetime.now(timezone.utc)).total_seconds() > 3
            row = db.session.get(WorkerJobError, job["id"])
            assert row.task_name == "send_activation_email"
            assert row.error_message == "MailDeliveryError: Brevo answered with status 503"

            for _ in range(worker.MAIL_MAX_RUNS - 1):
                _make_due()
                _run_worker("default")

        (job,) = _mail_jobs()
        assert job["status"] == "failed"
        assert job["attempts"] == worker.MAIL_MAX_RUNS
        assert send.call_count == worker.MAIL_MAX_RUNS

    def test_permanent_error_is_not_retried(self, app, mail_user):
        from services import mail

        mail.notify_activation_email(mail_user.id)
        with patch("services.mail._send", side_effect=mail.PermanentMailError("status 400")) as send:
            _run_worker("default")

        (job,) = _mail_jobs()
        assert job["status"] == "failed"
        assert send.call_count == 1

    def test_stalled_mail_job_is_retried(self, app, mail_user):
        from services import mail

        mail.notify_activation_email(mail_user.id)
        _kill_worker_mid_job()
        _recover()

        (job,) = _mail_jobs()
        assert job["status"] == "todo" and job["attempts"] == 1

    def test_admin_retry_requeues_failed_mail_job(self, app, mail_user):
        from models import WorkerJobError
        from services import mail, workers

        mail.notify_activation_email(mail_user.id)
        with patch("services.mail._send", side_effect=mail.PermanentMailError("status 400")):
            _run_worker("default")
        (job,) = _mail_jobs()
        assert job["status"] == "failed"

        with app.test_request_context():
            assert workers.retry_failed_job(job["id"], mail_user.id) is True

        (job,) = _mail_jobs()
        assert job["status"] == "todo"
        assert db.session.get(WorkerJobError, job["id"]) is None

    def test_failed_mail_job_target_shows_user(self, app):
        from services.workers import _target

        assert _target({"user_id": 4}) == "4"
        assert _target({"ticket_id": 9, "subject": "x"}) == "9"
        assert _target({"email": "a@test.com", "ip": "1.2.3.4"}) == "a@test.com"
        assert _target({"summary": "x"}) is None


class TestCloseWorkerApp:
    @pytest.fixture(autouse=True)
    def _clean(self):
        worker.close_worker_app()
        yield
        worker.close_worker_app()

    def test_close_worker_app_closes_sync_pool(self):
        worker.open_for_defer()
        sync_connector = worker.worker_app.connector._sync_connector
        pool = sync_connector._pool
        assert pool is not None and not pool.closed

        worker.close_worker_app()

        assert pool.closed
        assert worker.worker_app.connector._sync_connector is None

    def test_close_worker_app_idempotent_when_not_opened(self):
        assert worker.worker_app.connector._sync_connector is None

        worker.close_worker_app()
        worker.close_worker_app()

        assert worker.worker_app.connector._sync_connector is None

    def test_close_worker_app_allows_reopen(self):
        worker.open_for_defer()
        first = worker.worker_app.connector._sync_connector._pool
        worker.close_worker_app()

        worker.open_for_defer()
        second = worker.worker_app.connector._sync_connector._pool

        assert second is not first
        assert not second.closed
