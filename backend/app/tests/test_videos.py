"""Tests for services/videos.py — validation, upload init, finalize, processing, ffmpeg parsing.

Object storage, ffmpeg and Redis are mocked; the database is real. The queue
round trip of finalize/process is covered end to end in test_worker.py.
"""

import io
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image as PilImage
from sqlalchemy import select

from models import (
    db,
    AuditLog,
    AuditLogType,
    Library,
    User,
    Video,
    VideoProcessingStatus,
)
from services import videos as videos_service
from services.videos import (
    STEP_DOWNLOADING,
    STEP_PROBING,
    STEP_SAVING,
    STEP_UPLOADING,
    clear_video_step,
    finalize_video_upload,
    get_video_step,
    init_video_upload,
    process_video,
    set_video_step,
    validate_video_init,
    _extract_video_info,
)

VIDEO_UUID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def owner():
    user = User(email="photo@test.com", active=True)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def library(owner):
    lib = Library(user_id=owner.id, name="Lib")
    db.session.add(lib)
    db.session.commit()
    return lib


def _make_video(library, status=VideoProcessingStatus.uploading):
    video = Video(
        uuid=VIDEO_UUID,
        library_id=library.id,
        s3_key=f"{VIDEO_UUID}.mp4",
        original_filename="clip.mp4",
        content_type="video/mp4",
        size=1000,
        processing_status=status,
    )
    db.session.add(video)
    db.session.commit()
    return video


@pytest.fixture
def video(library):
    return _make_video(library)


@pytest.fixture
def storage():
    with patch("services.videos.storage") as st:
        st.object_exists.return_value = True
        st.create_presigned_put_url.return_value = "http://example.com/put"
        st.iter_object_chunks.side_effect = lambda key: iter([b"fake ", b"video"])
        yield st


@pytest.fixture(autouse=True)
def no_leftover_steps():
    videos_service._steps_in_memory.clear()
    yield
    videos_service._steps_in_memory.clear()


class TestValidateVideoInit:
    @pytest.mark.parametrize(
        "content_type", ["video/mp4", "video/quicktime", "video/webm", "video/x-m4v"]
    )
    def test_allowed_types_pass(self, content_type):
        validate_video_init(content_type, 1000, "clip.mp4")

    @pytest.mark.parametrize(
        "content_type", ["image/jpeg", "application/pdf", "video/avi", "", "VIDEO/MP4"]
    )
    def test_unsupported_types_are_rejected(self, content_type):
        with pytest.raises(ValueError, match="MP4, MOV, WebM"):
            validate_video_init(content_type, 1000, "clip.mp4")

    def test_size_at_limit_passes(self):
        with patch("services.videos.MAX_VIDEO_FILE_SIZE", 2 * 1024 * 1024):
            validate_video_init("video/mp4", 2 * 1024 * 1024, "clip.mp4")

    def test_size_over_limit_is_rejected_with_limit_in_message(self):
        with patch("services.videos.MAX_VIDEO_FILE_SIZE", 2 * 1024 * 1024):
            with pytest.raises(ValueError, match=r"File too large \(max 2 MB\)"):
                validate_video_init("video/mp4", 2 * 1024 * 1024 + 1, "clip.mp4")

    def test_empty_filename_is_rejected(self):
        with pytest.raises(ValueError, match="Filename is required"):
            validate_video_init("video/mp4", 1000, "")

    def test_type_is_checked_before_size_and_filename(self):
        with pytest.raises(ValueError, match="MP4, MOV, WebM"):
            validate_video_init("image/png", 10**12, "")


class TestInitVideoUpload:
    @pytest.fixture(autouse=True)
    def request_context(self, app):
        """The audit log reads the client IP from the current request."""
        with app.test_request_context():
            yield

    def test_creates_uploading_row_and_presigned_url(self, owner, library, storage):
        video, url = init_video_upload(library, owner, "My Clip.mov", "video/quicktime", 4321)

        assert url == "http://example.com/put"
        assert video.uuid and video.s3_key == f"{video.uuid}.mov"
        assert video.library_id == library.id
        assert video.original_filename == "My Clip.mov"
        assert video.content_type == "video/quicktime"
        assert video.size == 4321
        assert video.processing_status == VideoProcessingStatus.uploading
        assert video.is_external is False
        assert db.session.execute(select(Video)).scalar_one().id == video.id

    def test_storage_key_and_ttl(self, owner, library, storage):
        video, _ = init_video_upload(library, owner, "c.mp4", "video/mp4", 10)

        storage.ensure_bucket.assert_called_once()
        storage.create_presigned_put_url.assert_called_once_with(
            f"photos/{owner.id}/{library.id}/originals/{video.uuid}.mp4",
            "video/mp4",
            expires_in=3600,
        )

    @pytest.mark.parametrize(
        "content_type,ext",
        [
            ("video/mp4", "mp4"),
            ("video/quicktime", "mov"),
            ("video/webm", "webm"),
            ("video/x-m4v", "m4v"),
        ],
    )
    def test_extension_follows_content_type(self, owner, library, storage, content_type, ext):
        video, _ = init_video_upload(library, owner, "c", content_type, 10)
        assert video.s3_key.endswith(f".{ext}")

    def test_photographer_upload_is_logged_with_creator(self, owner, library, storage):
        video, _ = init_video_upload(library, owner, "c.mp4", "video/mp4", 10)

        log = db.session.execute(select(AuditLog)).scalar_one()
        assert log.audit_type == AuditLogType.video_uploaded
        assert log.creator_id == owner.id
        assert log.related_object_type == "video"
        assert log.related_object_id == video.uuid

    def test_public_upload_is_external_and_logged_without_creator(
        self, owner, library, storage
    ):
        video, _ = init_video_upload(
            library, owner, "c.mp4", "video/mp4", 10, is_external=True
        )

        assert video.is_external is True
        log = db.session.execute(select(AuditLog)).scalar_one()
        assert log.creator_id is None

    def test_storage_failure_leaves_no_row(self, owner, library, storage):
        storage.create_presigned_put_url.side_effect = RuntimeError("s3 down")

        with pytest.raises(RuntimeError):
            init_video_upload(library, owner, "c.mp4", "video/mp4", 10)

        assert db.session.execute(select(Video)).scalars().all() == []
        assert db.session.execute(select(AuditLog)).scalars().all() == []


class TestFinalizeVideoUpload:
    def test_missing_object_raises_and_keeps_status(self, video, storage):
        storage.object_exists.return_value = False

        with pytest.raises(ValueError, match="not found in storage"):
            finalize_video_upload(video)

        storage.object_exists.assert_called_once_with(video.storage_path("originals"))
        assert video.processing_status == VideoProcessingStatus.uploading

    def test_success_sets_processing_and_defers_with_locks(self, video, storage):
        import worker

        task = MagicMock()
        with patch.object(worker, "open_for_defer") as opened, patch.object(
            worker, "process_video_task", task
        ):
            finalize_video_upload(video)

        opened.assert_called_once()
        task.configure.assert_called_once_with(
            lock=f"video-{video.uuid}", queueing_lock=f"video-{video.uuid}"
        )
        task.configure.return_value.defer.assert_called_once_with(video_uuid=video.uuid)
        assert video.processing_status == VideoProcessingStatus.processing

    def test_already_enqueued_is_not_an_error(self, video, storage):
        import worker
        from procrastinate.exceptions import AlreadyEnqueued

        task = MagicMock()
        task.configure.return_value.defer.side_effect = AlreadyEnqueued("queued")
        with patch.object(worker, "open_for_defer"), patch.object(
            worker, "process_video_task", task
        ):
            finalize_video_upload(video)

        assert video.processing_status == VideoProcessingStatus.processing

    def test_defer_failure_rolls_back_to_uploading_and_reraises(self, video, storage):
        import worker

        task = MagicMock()
        task.configure.return_value.defer.side_effect = RuntimeError("db down")
        with patch.object(worker, "open_for_defer"), patch.object(
            worker, "process_video_task", task
        ):
            with pytest.raises(RuntimeError, match="db down"):
                finalize_video_upload(video)

        db.session.expire_all()
        reloaded = db.session.execute(select(Video)).scalar_one()
        assert reloaded.processing_status == VideoProcessingStatus.uploading


def _frame_info(size=(1280, 720), mode="RGB", **overrides):
    info = {
        "frame": PilImage.new(mode, size, "blue"),
        "width": size[0],
        "height": size[1],
        "duration_ms": 4000,
        "video_codec": "h264",
        "audio_codec": "aac",
        "bitrate": 1_000_000,
        "hevc_warning": False,
    }
    info.update(overrides)
    return info


def _reload():
    db.session.expire_all()
    return db.session.execute(select(Video)).scalar_one()


class TestProcessVideo:
    def test_unknown_uuid_raises(self, storage):
        with pytest.raises(ValueError, match="not found"):
            process_video(VIDEO_UUID)

    def test_ready_video_is_left_alone(self, library, storage):
        _make_video(library, status=VideoProcessingStatus.ready)
        with patch("services.videos._extract_video_info") as probe:
            process_video(VIDEO_UUID)

        storage.iter_object_chunks.assert_not_called()
        storage.upload_fileobj.assert_not_called()
        probe.assert_not_called()

    def test_success_marks_ready_and_stores_metadata(self, video, storage):
        info = _frame_info(
            duration_ms=4321,
            video_codec="hevc",
            audio_codec="opus",
            bitrate=2_500_000,
            hevc_warning=True,
        )
        with patch("services.videos._extract_video_info", return_value=info):
            process_video(VIDEO_UUID)

        done = _reload()
        assert done.processing_status == VideoProcessingStatus.ready
        assert (done.width, done.height) == (1280, 720)
        assert done.duration_ms == 4321
        assert done.video_codec == "hevc"
        assert done.audio_codec == "opus"
        assert done.bitrate == 2_500_000
        assert done.hevc_warning is True

    def test_downloads_original_into_a_temp_file_and_removes_it(self, video, storage):
        seen = {}

        def probe(path):
            with open(path, "rb") as fh:
                seen["path"] = path
                seen["content"] = fh.read()
                seen["suffix"] = os.path.splitext(path)[1]
            return _frame_info()

        with patch("services.videos._extract_video_info", side_effect=probe):
            process_video(VIDEO_UUID)

        storage.iter_object_chunks.assert_called_once_with(video.storage_path("originals"))
        assert seen["content"] == b"fake video"
        assert seen["suffix"] == ".mp4"
        assert not os.path.exists(seen["path"])

    def test_thumbnail_is_scaled_rgb_jpeg_at_thumb_key(self, video, storage):
        uploads = []

        def capture(fileobj, key, content_type):
            uploads.append((fileobj.read(), key, content_type))

        storage.upload_fileobj.side_effect = capture
        with patch(
            "services.videos._extract_video_info",
            return_value=_frame_info(size=(1920, 1080), mode="RGBA"),
        ):
            process_video(VIDEO_UUID)

        ((data, key, content_type),) = uploads
        assert key == video.storage_path("thumbs")
        assert key.endswith(".jpg")
        assert content_type == "image/jpeg"
        thumb = PilImage.open(io.BytesIO(data))
        assert thumb.format == "JPEG"
        assert thumb.mode == "RGB"
        assert max(thumb.size) == 600
        assert thumb.size == (600, 338)

    def test_small_frame_is_not_enlarged(self, video, storage):
        uploads = []
        storage.upload_fileobj.side_effect = lambda f, k, c: uploads.append(f.read())
        with patch(
            "services.videos._extract_video_info", return_value=_frame_info(size=(320, 240))
        ):
            process_video(VIDEO_UUID)

        assert PilImage.open(io.BytesIO(uploads[0])).size == (320, 240)

    def test_evicts_public_and_storage_caches(self, video, library, owner, storage):
        with patch("services.videos._extract_video_info", return_value=_frame_info()), patch(
            "services.videos.cache_delete_pattern"
        ) as pattern, patch("services.videos.cache_delete") as single:
            process_video(VIDEO_UUID)

        pattern.assert_called_once_with(f"public:library:{library.uuid}:*")
        single.assert_any_call(f"user:storage:{owner.id}")

    def test_steps_are_reported_in_order_and_cleared(self, video, storage):
        steps = []
        with patch("services.videos._extract_video_info", return_value=_frame_info()), patch(
            "services.videos.set_video_step", side_effect=lambda u, s: steps.append(s)
        ):
            process_video(VIDEO_UUID)

        assert steps == [STEP_DOWNLOADING, STEP_PROBING, STEP_UPLOADING, STEP_SAVING]
        assert get_video_step(VIDEO_UUID) is None

    def test_probe_failure_reraises_and_clears_step(self, library, storage):
        _make_video(library, status=VideoProcessingStatus.processing)
        with patch(
            "services.videos._extract_video_info", side_effect=ValueError("no frame")
        ):
            with pytest.raises(ValueError, match="no frame"):
                process_video(VIDEO_UUID)

        assert get_video_step(VIDEO_UUID) is None
        assert _reload().processing_status == VideoProcessingStatus.processing
        storage.upload_fileobj.assert_not_called()

    def test_probe_failure_removes_temp_file(self, library, storage):
        _make_video(library, status=VideoProcessingStatus.processing)
        seen = {}

        def probe(path):
            seen["path"] = path
            raise ValueError("no frame")

        with patch("services.videos._extract_video_info", side_effect=probe):
            with pytest.raises(ValueError):
                process_video(VIDEO_UUID)

        assert not os.path.exists(seen["path"])

    def test_download_failure_reraises_and_clears_step(self, library, storage):
        _make_video(library, status=VideoProcessingStatus.processing)
        storage.iter_object_chunks.side_effect = RuntimeError("s3 down")

        with pytest.raises(RuntimeError, match="s3 down"):
            process_video(VIDEO_UUID)

        assert get_video_step(VIDEO_UUID) is None
        assert _reload().processing_status == VideoProcessingStatus.processing

    def test_thumbnail_upload_failure_keeps_status_unchanged(self, library, storage):
        _make_video(library, status=VideoProcessingStatus.processing)
        storage.upload_fileobj.side_effect = RuntimeError("s3 down")
        with patch("services.videos._extract_video_info", return_value=_frame_info()):
            with pytest.raises(RuntimeError):
                process_video(VIDEO_UUID)

        assert _reload().processing_status == VideoProcessingStatus.processing


FFMPEG_STDERR = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'in.mp4':
  Duration: 00:01:02.34, start: 0.000000, bitrate: 1500 kb/s
  Stream #0:0(und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 1920x1080, 1400 kb/s
  Stream #0:1(und): Audio: AAC (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp
At least one output file must be specified
"""


def _jpeg(size=(64, 48)):
    buf = io.BytesIO()
    PilImage.new("RGB", size, "red").save(buf, format="JPEG")
    return buf.getvalue()


def _fake_run(stderr, frames):
    """subprocess.run stand-in: the first call is the probe, the rest extract frames.

    ``frames`` maps the -ss seek value to the bytes ffmpeg would print.
    """
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if "-ss" not in cmd:
            return SimpleNamespace(stderr=stderr, stdout=b"")
        seek = int(cmd[cmd.index("-ss") + 1])
        return SimpleNamespace(stderr="", stdout=frames.get(seek, b""))

    run.calls = calls
    return run


@pytest.fixture
def ffmpeg():
    with patch("imageio_ffmpeg.get_ffmpeg_exe", return_value="/usr/bin/ffmpeg"):
        yield


@pytest.mark.usefixtures("ffmpeg")
class TestExtractVideoInfo:
    def _run(self, stderr=FFMPEG_STDERR, frames=None):
        run = _fake_run(stderr, frames if frames is not None else {1: _jpeg()})
        with patch("services.videos.subprocess.run", side_effect=run):
            info = _extract_video_info("/tmp/in.mp4")
        return info, run

    def test_parses_probe_output(self):
        info, _ = self._run()

        assert info["video_codec"] == "h264"
        assert info["audio_codec"] == "aac"
        assert info["bitrate"] == 1_500_000
        assert info["duration_ms"] == (62 * 1000) + 340
        assert info["hevc_warning"] is False

    def test_dimensions_come_from_the_extracted_frame(self):
        info, _ = self._run(frames={1: _jpeg((64, 48))})
        assert (info["width"], info["height"]) == (64, 48)
        assert info["frame"].size == (64, 48)
        assert info["frame"].mode == "RGB"

    def test_duration_with_hours(self):
        stderr = FFMPEG_STDERR.replace("00:01:02.34", "01:02:03.05")
        info, _ = self._run(stderr)
        assert info["duration_ms"] == ((3600 + 120 + 3) * 1000) + 50

    @pytest.mark.parametrize("codec", ["hevc", "h265", "HEVC"])
    def test_hevc_sets_warning(self, codec):
        info, _ = self._run(FFMPEG_STDERR.replace("Video: h264", f"Video: {codec}"))
        assert info["video_codec"] == codec.lower()
        assert info["hevc_warning"] is True

    def test_missing_streams_and_fields_are_none(self):
        info, _ = self._run("Input #0, matroska, from 'in.webm':\n")
        assert info["video_codec"] is None
        assert info["audio_codec"] is None
        assert info["bitrate"] is None
        assert info["duration_ms"] is None
        assert info["hevc_warning"] is False

    def test_frame_is_taken_at_one_second_first(self):
        _, run = self._run(frames={1: _jpeg()})

        probe, *extracts = run.calls
        assert probe[:3] == ["/usr/bin/ffmpeg", "-i", "/tmp/in.mp4"]
        assert len(extracts) == 1
        assert extracts[0][extracts[0].index("-ss") + 1] == "1"

    def test_falls_back_to_first_frame_for_short_clips(self):
        info, run = self._run(frames={1: b"", 0: _jpeg((32, 32))})

        seeks = [c[c.index("-ss") + 1] for c in run.calls if "-ss" in c]
        assert seeks == ["1", "0"]
        assert info["width"] == 32

    def test_no_frame_at_all_raises(self):
        with pytest.raises(ValueError, match="Could not extract video frame"):
            self._run(frames={})

    def test_subprocess_calls_are_bounded_by_the_job_timeout(self):
        run = _fake_run(FFMPEG_STDERR, {1: _jpeg()})
        with patch("services.videos.subprocess.run", side_effect=run) as p, patch(
            "services.videos.VIDEO_JOB_TIMEOUT_SECONDS", 42
        ):
            _extract_video_info("/tmp/in.mp4")

        assert p.call_count == 2
        assert all(c.kwargs["timeout"] == 42 for c in p.call_args_list)


class TestVideoSteps:
    def test_in_memory_without_redis(self):
        with patch("services.videos.get_redis", return_value=None):
            assert get_video_step(VIDEO_UUID) is None
            set_video_step(VIDEO_UUID, STEP_PROBING)
            assert get_video_step(VIDEO_UUID) == STEP_PROBING
            set_video_step(VIDEO_UUID, STEP_SAVING)
            assert get_video_step(VIDEO_UUID) == STEP_SAVING
            clear_video_step(VIDEO_UUID)
            assert get_video_step(VIDEO_UUID) is None

    def test_in_memory_steps_are_per_video(self):
        with patch("services.videos.get_redis", return_value=None):
            set_video_step("a", STEP_PROBING)
            set_video_step("b", STEP_SAVING)
            clear_video_step("a")
            assert get_video_step("a") is None
            assert get_video_step("b") == STEP_SAVING

    def test_clearing_an_unknown_step_is_harmless(self):
        with patch("services.videos.get_redis", return_value=None):
            clear_video_step("never-set")

    def test_redis_set_uses_key_and_ttl(self):
        with patch("services.videos.get_redis", return_value=MagicMock()), patch(
            "services.videos.cache_set"
        ) as cset:
            set_video_step(VIDEO_UUID, STEP_UPLOADING)

        cset.assert_called_once_with(
            f"worker:video-step:{VIDEO_UUID}", STEP_UPLOADING, ttl=3600
        )
        assert videos_service._steps_in_memory == {}

    def test_redis_get_reads_the_cache(self):
        with patch("services.videos.get_redis", return_value=MagicMock()), patch(
            "services.videos.cache_get", return_value=STEP_SAVING
        ) as cget:
            assert get_video_step(VIDEO_UUID) == STEP_SAVING

        cget.assert_called_once_with(f"worker:video-step:{VIDEO_UUID}")

    def test_redis_clear_deletes_the_key_and_the_local_copy(self):
        videos_service._steps_in_memory[VIDEO_UUID] = STEP_PROBING
        with patch("services.videos.get_redis", return_value=MagicMock()), patch(
            "services.videos.cache_delete"
        ) as cdel:
            clear_video_step(VIDEO_UUID)

        cdel.assert_called_once_with(f"worker:video-step:{VIDEO_UUID}")
        assert VIDEO_UUID not in videos_service._steps_in_memory
