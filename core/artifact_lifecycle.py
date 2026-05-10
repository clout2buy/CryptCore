"""Artifact lifecycle tracking for generated files."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ArtifactRecord:
    path: str
    state: str
    requested_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    writes: int = 0
    opened: bool = False
    verified: bool = False
    notes: list[str] = field(default_factory=list)


_LOCK = threading.RLock()
_RECORDS: dict[str, ArtifactRecord] = {}


def clear() -> None:
    with _LOCK:
        _RECORDS.clear()


def record_write(path: str | Path, *, note: str = "") -> ArtifactRecord:
    key = _key(path)
    with _LOCK:
        rec = _RECORDS.get(key)
        if rec is None:
            rec = ArtifactRecord(path=key, state="created")
            _RECORDS[key] = rec
        rec.state = "created"
        rec.updated_at = time.time()
        rec.writes += 1
        if note:
            rec.notes.append(note)
    _record_evidence(rec, "artifact_write")
    return rec


def record_open(path: str | Path) -> ArtifactRecord:
    key = _key(path)
    with _LOCK:
        rec = _RECORDS.get(key) or ArtifactRecord(path=key, state="opened")
        rec.state = "opened"
        rec.opened = True
        rec.updated_at = time.time()
        _RECORDS[key] = rec
    _record_evidence(rec, "artifact_open")
    return rec


def record_verification(path: str | Path, *, ok: bool, note: str = "") -> ArtifactRecord:
    key = _key(path)
    with _LOCK:
        rec = _RECORDS.get(key) or ArtifactRecord(path=key, state="verified" if ok else "failed")
        rec.state = "verified" if ok else "failed"
        rec.verified = bool(ok)
        rec.updated_at = time.time()
        if note:
            rec.notes.append(note)
        _RECORDS[key] = rec
    _record_evidence(rec, "artifact_verification")
    return rec


def records() -> list[ArtifactRecord]:
    with _LOCK:
        return list(_RECORDS.values())


def was_written(path: str | Path) -> bool:
    rec = _RECORDS.get(_key(path))
    return bool(rec and rec.writes > 0)


def needs_diagnosis(path: str | Path) -> bool:
    rec = _RECORDS.get(_key(path))
    return bool(rec and rec.writes >= 3 and not rec.opened and not rec.verified)


def snapshot() -> list[dict[str, Any]]:
    return [asdict(item) for item in records()]


def _key(path: str | Path) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def _record_evidence(rec: ArtifactRecord, source: str) -> None:
    try:
        from . import evidence

        evidence.record(
            "artifact",
            source,
            f"{rec.state}: {rec.path}",
            details=asdict(rec),
        )
    except Exception:
        return
