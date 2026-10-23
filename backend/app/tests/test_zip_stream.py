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
