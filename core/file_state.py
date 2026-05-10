"""Session-scoped file read/write state.

The edit tool uses this to enforce the core invariant: do not modify an
existing file unless Crypt has read it in the current session and it has not
changed since that read.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileSnapshot:
    path: str
    mtime_ns: int
    size: int
    digest: str
    partial: bool
    offset: int | None = None
    limit: int | None = None


_READS: dict[str, FileSnapshot] = {}
_LOCK = threading.RLock()


def _key(path: Path) -> str:
    return str(path.resolve()).lower()


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_read(
    path: Path,
    data: bytes,
    *,
    offset: int | None = None,
    limit: int | None = None,
    partial: bool | None = None,
) -> None:
    st = path.stat()
    with _LOCK:
        _READS[_key(path)] = FileSnapshot(
            path=str(path.resolve()),
            mtime_ns=st.st_mtime_ns,
            size=st.st_size,
            digest=_digest_bytes(data),
            partial=bool(offset or limit) if partial is None else partial,
            offset=offset,
            limit=limit,
        )


def record_write(path: Path) -> None:
    if not path.exists() or not path.is_file():
        _READS.pop(_key(path), None)
        return
    data = path.read_bytes()
    record_read(path, data)


def forget(path: Path) -> None:
    with _LOCK:
        _READS.pop(_key(path), None)


def clear() -> None:
    with _LOCK:
        _READS.clear()


def status(path: Path) -> FileSnapshot | None:
    with _LOCK:
        return _READS.get(_key(path))


def snapshot() -> dict[str, FileSnapshot]:
    with _LOCK:
        return dict(_READS)


def restore(state: dict[str, FileSnapshot]) -> None:
    with _LOCK:
        _READS.clear()
        _READS.update(state)


def assert_fresh_for_edit(path: Path) -> None:
    if not path.exists():
        return
    with _LOCK:
        snap = _READS.get(_key(path))
    if snap is None:
        raise PermissionError(
            "read-before-edit invariant: file has not been read in this session. "
            "Use read_file first, then edit_file."
        )
    if snap.partial:
        raise PermissionError(
            "read-before-edit invariant: only a partial range was read. "
            "Read the full file before editing it."
        )
    st = path.stat()
    if st.st_mtime_ns == snap.mtime_ns and st.st_size == snap.size:
        return
    current = path.read_bytes()
    if _digest_bytes(current) == snap.digest:
        # Timestamp changed without content changing (common with sync tools).
        record_read(path, current)
        return
    raise RuntimeError(
        "file changed since Crypt read it. Read it again before editing so "
        "user or formatter changes are not overwritten."
    )
