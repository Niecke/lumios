import io
import time
import zipfile
from datetime import datetime

import pytest

from services.zip_stream import stream_zip


@pytest.fixture(autouse=True)
def _with_app(app):
    """The autouse clean_db fixture needs an application context for its teardown."""


def _build(entries):
    body = b"".join(stream_zip(entries))
    return zipfile.ZipFile(io.BytesIO(body))


def _chunks(data=b"x"):
    return lambda: [data]


def test_default_timestamp_is_now():
    before = time.localtime()[:6]
    zf = _build([("a.jpg", _chunks())])
    after = time.localtime()[:6]
    dt = zf.getinfo("a.jpg").date_time
    assert dt != (1980, 1, 1, 0, 0, 0)
    assert before <= dt <= after or before[:5] <= dt[:5] <= after[:5]


def test_none_timestamp_falls_back_to_now():
    zf = _build([("a.jpg", _chunks(), None)])
    assert zf.getinfo("a.jpg").date_time[0] >= 2024


def test_explicit_datetime_and_tuple():
    zf = _build(
        [
            ("a.jpg", _chunks(), datetime(2023, 5, 17, 10, 20, 30)),
            ("b.jpg", _chunks(), (2021, 1, 2, 3, 4, 6)),
        ]
    )
    assert zf.getinfo("a.jpg").date_time == (2023, 5, 17, 10, 20, 30)
    assert zf.getinfo("b.jpg").date_time == (2021, 1, 2, 3, 4, 6)


def test_pre_1980_is_clamped():
    zf = _build(
        [
            ("a.jpg", _chunks(), datetime(1970, 1, 1)),
            ("b.jpg", _chunks(), (1969, 12, 31, 23, 59, 59)),
        ]
    )
    assert zf.getinfo("a.jpg").date_time == (1980, 1, 1, 0, 0, 0)
    assert zf.getinfo("b.jpg").date_time == (1980, 1, 1, 0, 0, 0)


def test_duplicate_filenames_keep_timestamps():
    ts = datetime(2022, 2, 3, 4, 5, 6)
    zf = _build([("same.jpg", _chunks(b"1"), ts), ("same.jpg", _chunks(b"2"), ts)])
    assert zf.namelist() == ["same.jpg", "same (1).jpg"]
    assert all(i.date_time == (2022, 2, 3, 4, 5, 6) for i in zf.infolist())
    assert zf.read("same (1).jpg") == b"2"


def test_empty_entries_generate_a_valid_empty_zip():
    body = b"".join(stream_zip([]))

    zf = zipfile.ZipFile(io.BytesIO(body))
    assert zf.namelist() == []
    assert zf.testzip() is None


def test_single_file_content_is_streamed_unchanged():
    payload = bytes(range(256)) * 10
    zf = _build([("a.bin", _chunks(payload))])
    assert zf.read("a.bin") == payload
    assert zf.testzip() is None


def test_multi_chunk_file_is_reassembled_in_order():
    chunks = [b"first-", b"second-", b"", b"third"]
    zf = _build([("a.txt", lambda: iter(chunks))])
    assert zf.read("a.txt") == b"first-second-third"


def test_multiple_entries_keep_their_own_content():
    zf = _build(
        [
            ("a.jpg", _chunks(b"AAA")),
            ("b.mp4", lambda: iter([b"B" * 100_000, b"B" * 5])),
            ("empty.bin", lambda: iter([])),
        ]
    )
    assert zf.namelist() == ["a.jpg", "b.mp4", "empty.bin"]
    assert zf.read("a.jpg") == b"AAA"
    assert zf.read("b.mp4") == b"B" * 100_005
    assert zf.read("empty.bin") == b""
    assert zf.testzip() is None


def test_entries_are_stored_uncompressed():
    zf = _build([("a.jpg", _chunks(b"x" * 1000))])
    assert zf.getinfo("a.jpg").compress_type == zipfile.ZIP_STORED


def test_stream_yields_incrementally_and_not_empty_chunks():
    pieces = list(stream_zip([("a.bin", lambda: iter([b"x" * 10, b"y" * 10]))]))
    assert len(pieces) > 1
    assert all(pieces)


def test_each_entry_factory_is_called_once():
    calls = []

    def factory():
        calls.append(1)
        return iter([b"x"])

    _build([("a", factory)])
    assert calls == [1]


def test_post_2107_date_is_clamped():
    zf = _build(
        [
            ("a.jpg", _chunks(), datetime(2200, 6, 1, 12, 0, 0)),
            ("b.jpg", _chunks(), (2108, 1, 1, 0, 0, 0)),
        ]
    )
    assert zf.getinfo("a.jpg").date_time == (2107, 12, 31, 23, 59, 58)
    assert zf.getinfo("b.jpg").date_time == (2107, 12, 31, 23, 59, 58)


def test_zip_date_time_boundaries():
    from services.zip_stream import _zip_date_time

    assert _zip_date_time((1980, 1, 1, 0, 0, 0)) == (1980, 1, 1, 0, 0, 0)
    assert _zip_date_time((2107, 12, 31, 23, 59, 58)) == (2107, 12, 31, 23, 59, 58)
    assert _zip_date_time((2108, 1, 1, 0, 0, 0)) == (2107, 12, 31, 23, 59, 58)
    assert _zip_date_time(datetime(1979, 12, 31, 23, 59, 59)) == (1980, 1, 1, 0, 0, 0)
    # extra fields of a time.struct_time-like tuple are ignored
    assert _zip_date_time((2020, 2, 3, 4, 5, 6, 1, 34, 0)) == (2020, 2, 3, 4, 5, 6)
