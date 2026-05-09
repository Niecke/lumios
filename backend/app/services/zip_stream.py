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
import zipfile
from typing import Callable, Iterable, Iterator


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


def stream_zip(
    entries: Iterable[tuple[str, Callable[[], Iterable[bytes]]]],
) -> Iterator[bytes]:
    """Yield the bytes of a ZIP archive built from ``entries``.

    Each entry is a ``(filename, chunk_iterator_factory)`` pair. The factory is
    called once and is expected to return an iterator that yields the file's
    raw bytes. Filenames are deduplicated within the archive.
    """
    buf = _ChunkBuffer()
    used: dict[str, int] = {}
    with zipfile.ZipFile(
        buf, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True
    ) as zf:
        for filename, get_chunks in entries:
            info = zipfile.ZipInfo(_unique_name(filename, used))
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
