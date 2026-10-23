"""Streaming ZIP writer.

Builds a ZIP archive on the fly and yields it as a sequence of byte chunks,
suitable for use as the body of a Flask streaming response. JPEG/PNG sources
are already compressed, so entries are stored without further compression
(ZIP_STORED) — this keeps CPU work negligible and the throughput close to
straight S3 → client byte forwarding.

The archive is written through an unseekable buffer so memory use stays
bounded by the size of the chunks currently in flight, regardless of the
total archive size.
"""

import os
import time
import zipfile
from datetime import datetime
from typing import Callable, Iterable, Iterator, Union

DateTime = Union[datetime, tuple, None]

# ZIP stores DOS timestamps, which cannot represent anything before 1980.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class _ChunkBuffer:
    """Append-only file-like that ZipFile treats as a non-seekable stream."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._pos = 0

    def write(self, data: bytes) -> int:
        if data:
            self._chunks.append(bytes(data))
            self._pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self._pos

    def flush(self) -> None:
        pass

    def drain(self) -> bytes:
        if not self._chunks:
            return b""
        out = b"".join(self._chunks)
        self._chunks.clear()
        return out


def _unique_name(filename: str, used: dict[str, int]) -> str:
    """Disambiguate duplicate filenames by appending a counter before the extension."""
    if filename not in used:
        used[filename] = 1
        return filename
    used[filename] += 1
    base, ext = os.path.splitext(filename)
    return f"{base} ({used[filename] - 1}){ext}"


def _zip_date_time(value: DateTime) -> tuple:
    """Normalise ``value`` to a valid ZIP ``(Y, M, D, h, m, s)`` tuple.

    ``None`` means "now". Anything before 1980 (or beyond the DOS range) is
    clamped, since ZipInfo raises on it and DOS timestamps cannot store it.
    """
    if value is None:
        return time.localtime()[:6]
    if isinstance(value, datetime):
        value = value.timetuple()
    dt = tuple(value)[:6]
    if dt < _ZIP_EPOCH:
        return _ZIP_EPOCH
    if dt[0] > 2107:
        return (2107, 12, 31, 23, 59, 58)
    return dt


def stream_zip(
    entries: Iterable[
        tuple[str, Callable[[], Iterable[bytes]]]
        | tuple[str, Callable[[], Iterable[bytes]], DateTime]
    ],
) -> Iterator[bytes]:
    """Yield the bytes of a ZIP archive built from ``entries``.

    Each entry is a ``(filename, chunk_iterator_factory)`` pair. The factory is
    called once and is expected to return an iterator that yields the file's
    raw bytes. An optional third element sets the member's modification time
    (``datetime`` or 6-tuple); if omitted or ``None`` the current time is used.
    Filenames are deduplicated within the archive.
    """
    buf = _ChunkBuffer()
    used: dict[str, int] = {}
    with zipfile.ZipFile(
        buf, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True
    ) as zf:
        for entry_spec in entries:
            filename, get_chunks = entry_spec[0], entry_spec[1]
            date_time = entry_spec[2] if len(entry_spec) > 2 else None
            info = zipfile.ZipInfo(
                _unique_name(filename, used), date_time=_zip_date_time(date_time)
            )
            with zf.open(info, mode="w", force_zip64=True) as entry:
                for chunk in get_chunks():
                    entry.write(chunk)
                    drained = buf.drain()
                    if drained:
                        yield drained
            drained = buf.drain()
            if drained:
                yield drained
    drained = buf.drain()
    if drained:
        yield drained
