"""services/covers.py: layout, sources, empty/deleted handling, failures, cover_url."""

import io
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from PIL import Image as PilImage

from models import Image, Library, User, db
from services.covers import (
    COVER_HEIGHT,
    COVER_WIDTH,
    cover_url,
    generate_library_cover,
)

COLOURS = ["red", "lime", "blue", "yellow", "white", "black"]


def _jpeg(colour, size=(800, 600)) -> bytes:
    buf = io.BytesIO()
    PilImage.new("RGB", size, colour).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _client_error(code, status=404):
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "GetObject",
    )


@pytest.fixture
def owner():
    user = User(email="cover@test.com", active=True)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def library(owner):
    lib = Library(user_id=owner.id, name="Lib")
    db.session.add(lib)
    db.session.commit()
    return lib


def _add_images(library, count, deleted=()):
    """Images 0..count-1, image i created i minutes after the first (0 is the oldest)."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    images = []
    for i in range(count):
        img = Image(
            uuid=f"00000000-0000-0000-0000-{i:012d}",
            library_id=library.id,
            s3_key=f"img{i}.jpg",
            original_filename=f"img{i}.jpg",
            content_type="image/jpeg",
            size=10,
            created_at=base + timedelta(minutes=i),
            deleted_at=base if i in deleted else None,
        )
        db.session.add(img)
        images.append(img)
    db.session.commit()
    return images


@pytest.fixture
def st():
    """Patched storage: previews are solid JPEGs, colour taken from the key's file name."""
    with patch("services.covers.storage") as storage, patch(
        "services.covers.cache_delete_pattern"
    ) as cache:
        reads = []

        def get_bytes(key):
            reads.append(key)
            n = int(re.search(r"img(\d+)\.jpg", key).group(1))
            return _jpeg(COLOURS[n])

        storage.get_object_bytes.side_effect = get_bytes
        storage.reads = reads
        storage.cache = cache
        yield storage


def _uploaded(st):
    (call,) = st.upload_fileobj.call_args_list
    buf, key, content_type = call.args
    return PilImage.open(io.BytesIO(buf.getvalue())), key, content_type


def _centre(img, x, y):
    return img.getpixel((x, y))


def _is(pixel, colour):
    expected = PilImage.new("RGB", (1, 1), colour).getpixel((0, 0))
    return all(abs(a - b) < 40 for a, b in zip(pixel, expected))


class TestLayout:
    def test_grid_uses_four_newest_previews_in_order(self, st, library, owner):
        _add_images(library, 5)

        generate_library_cover(library.id)

        # newest first: img4, img3, img2, img1
        assert [re.search(r"img\d", k).group(0) for k in st.reads] == [
            "img4", "img3", "img2", "img1",
        ]
        assert all("/previews/" in k and "/originals/" not in k for k in st.reads)
        img, key, content_type = _uploaded(st)
        assert content_type == "image/jpeg"
        assert re.fullmatch(
            rf"photos/{owner.id}/{library.id}/covers/cover-[0-9a-f]{{8}}\.jpg", key
        )
        assert img.format == "JPEG"
        assert img.size == (COVER_WIDTH, COVER_HEIGHT)
        assert _is(_centre(img, 160, 100), COLOURS[4])
        assert _is(_centre(img, 480, 100), COLOURS[3])
        assert _is(_centre(img, 160, 300), COLOURS[2])
        assert _is(_centre(img, 480, 300), COLOURS[1])
        assert db.session.get(Library, library.id).cover_key == key

    def test_fewer_than_four_uses_newest_photo_only(self, st, library):
        _add_images(library, 2)

        generate_library_cover(library.id)

        img, _, _ = _uploaded(st)
        assert img.size == (COVER_WIDTH, COVER_HEIGHT)
        for x, y in ((10, 10), (630, 10), (10, 390), (320, 200), (630, 390)):
            assert _is(_centre(img, x, y), COLOURS[1])

    def test_never_reads_originals(self, st, library):
        _add_images(library, 6)

        generate_library_cover(library.id)

        assert st.reads and not any("originals" in k for k in st.reads)


class TestSources:
    def test_soft_deleted_images_are_not_read(self, st, library):
        _add_images(library, 5, deleted={4})

        generate_library_cover(library.id)

        assert not any("img4.jpg" in k for k in st.reads)
        assert len(st.reads) == 4

    def test_empty_library_does_nothing(self, st, library):
        generate_library_cover(library.id)

        st.get_object_bytes.assert_not_called()
        st.upload_fileobj.assert_not_called()
        st.delete_object.assert_not_called()
        assert db.session.get(Library, library.id).cover_key is None

    def test_all_images_deleted_resets_existing_cover(self, st, library):
        _add_images(library, 2, deleted={0, 1})
        library.cover_key = "photos/1/1/covers/cover-old.jpg"
        db.session.commit()

        generate_library_cover(library.id)

        st.upload_fileobj.assert_not_called()
        st.delete_object.assert_called_once_with("photos/1/1/covers/cover-old.jpg")
        assert db.session.get(Library, library.id).cover_key is None
        st.cache.assert_called()

    def test_missing_preview_is_skipped(self, st, library):
        _add_images(library, 3)
        original = st.get_object_bytes.side_effect

        def get_bytes(key):
            if "img2.jpg" in key:
                raise _client_error("NoSuchKey")
            return original(key)

        st.get_object_bytes.side_effect = get_bytes

        generate_library_cover(library.id)

        img, _, _ = _uploaded(st)
        assert _is(_centre(img, 320, 200), COLOURS[1])

    def test_all_previews_missing_gives_placeholder(self, st, library):
        _add_images(library, 3)
        library.cover_key = "photos/1/1/covers/cover-old.jpg"
        db.session.commit()
        st.get_object_bytes.side_effect = _client_error("NoSuchKey")

        generate_library_cover(library.id)

        st.upload_fileobj.assert_not_called()
        assert db.session.get(Library, library.id).cover_key is None

    def test_undecodable_preview_is_skipped(self, st, library):
        _add_images(library, 2)
        original = st.get_object_bytes.side_effect

        def get_bytes(key):
            if "img1.jpg" in key:
                return b"not an image"
            return original(key)

        st.get_object_bytes.side_effect = get_bytes

        generate_library_cover(library.id)

        img, _, _ = _uploaded(st)
        assert _is(_centre(img, 320, 200), COLOURS[0])

    @pytest.mark.parametrize(
        "error",
        [
            _client_error("InternalError", 500),
            EndpointConnectionError(endpoint_url="http://s3"),
        ],
    )
    def test_other_storage_errors_propagate(self, st, library, error):
        _add_images(library, 2)
        st.get_object_bytes.side_effect = error

        with pytest.raises((ClientError, EndpointConnectionError)):
            generate_library_cover(library.id)

        st.upload_fileobj.assert_not_called()


class TestRegeneration:
    def test_old_cover_deleted_after_new_one_is_set(self, st, library):
        _add_images(library, 2)
        library.cover_key = "photos/1/1/covers/cover-old.jpg"
        db.session.commit()
        seen = {}

        def delete(key):
            seen["cover_key_at_delete"] = (
                db.session.execute(
                    db.select(Library.cover_key).where(Library.id == library.id)
                ).scalar_one()
            )

        st.delete_object.side_effect = delete

        generate_library_cover(library.id)

        _, new_key, _ = _uploaded(st)
        st.delete_object.assert_called_once_with("photos/1/1/covers/cover-old.jpg")
        assert seen["cover_key_at_delete"] == new_key
        st.cache.assert_called()

    def test_failing_delete_of_old_cover_does_not_fail_job(self, st, library):
        _add_images(library, 2)
        library.cover_key = "photos/1/1/covers/cover-old.jpg"
        db.session.commit()
        st.delete_object.side_effect = _client_error("InternalError", 500)

        generate_library_cover(library.id)

        assert db.session.get(Library, library.id).cover_key != "photos/1/1/covers/cover-old.jpg"

    def test_upload_failure_keeps_old_cover(self, st, library):
        _add_images(library, 2)
        library.cover_key = "photos/1/1/covers/cover-old.jpg"
        db.session.commit()
        st.upload_fileobj.side_effect = EndpointConnectionError(endpoint_url="http://s3")

        with pytest.raises(EndpointConnectionError):
            generate_library_cover(library.id)

        assert db.session.get(Library, library.id).cover_key == "photos/1/1/covers/cover-old.jpg"
        st.delete_object.assert_not_called()

    def test_deleted_library_is_a_no_op(self, st, library):
        _add_images(library, 2)
        library.deleted_at = datetime.now(timezone.utc)
        db.session.commit()

        generate_library_cover(library.id)
        generate_library_cover(999999)

        st.get_object_bytes.assert_not_called()
        st.upload_fileobj.assert_not_called()

    def test_rerun_keeps_layout_and_one_current_cover(self, st, library):
        _add_images(library, 5)

        generate_library_cover(library.id)
        first = db.session.get(Library, library.id).cover_key
        st.upload_fileobj.reset_mock()
        generate_library_cover(library.id)

        img, second, _ = _uploaded(st)
        assert second != first
        assert db.session.get(Library, library.id).cover_key == second
        st.delete_object.assert_called_once_with(first)
        assert _is(_centre(img, 160, 100), COLOURS[4])
        assert _is(_centre(img, 480, 300), COLOURS[1])


class TestCoverUrl:
    def test_none_without_key(self, library):
        with patch("services.covers.storage") as st:
            assert cover_url(library) is None
            st.get_presigned_url.assert_not_called()

    def test_presigned_url_with_key(self, library):
        library.cover_key = "photos/1/1/covers/cover-a.jpg"
        with patch("services.covers.storage") as st:
            st.get_presigned_url.return_value = "http://signed"
            assert cover_url(library) == "http://signed"
            st.get_presigned_url.assert_called_once_with("photos/1/1/covers/cover-a.jpg")

    def test_none_when_presign_fails(self, library):
        library.cover_key = "photos/1/1/covers/cover-a.jpg"
        with patch("services.covers.storage") as st:
            st.get_presigned_url.side_effect = RuntimeError("boom")
            assert cover_url(library) is None
