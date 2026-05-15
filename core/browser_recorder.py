"""Durable visual browser activity recorder."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import artifact_studio, browser_operator, session, settings, work_threads


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BrowserRecording:
    recording_id: str
    cwd: str
    url: str
    title: str = ""
    status: str = "running"
    mission_id: str = ""
    thread_id: str = ""
    screenshots: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def recordings_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "browser" / "recordings.json"


def start_recording(
    cwd: str | Path,
    url: str,
    *,
    title: str = "",
    mission_id: str = "",
    thread_id: str = "",
    note: str = "",
) -> BrowserRecording:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    thread = _thread(root, mission_id=mission_id, thread_id=thread_id)
    recording = BrowserRecording(
        recording_id="browser_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        url=_clean(url, 1_000),
        title=_clean(title, 180),
        mission_id=mission_id or (thread.goal_id if thread else ""),
        thread_id=thread_id or (thread.thread_id if thread else ""),
        notes=[_clean(note, 800)] if note else [],
        created_at=now,
        updated_at=now,
    )
    rows = list_recordings(root, include_all=True)
    rows.insert(0, recording)
    _write(root, rows)
    return recording


def record_smoke(cwd: str | Path, result: browser_operator.BrowserSmokeResult, *, note: str = "") -> BrowserRecording:
    recording = start_recording(
        cwd,
        result.url,
        title=result.title,
        note=note or ("local browser smoke passed" if result.ok else result.error),
    )
    status = "verified" if result.ok else "failed"
    return update_recording(
        cwd,
        recording.recording_id,
        status=status,
        checks=result.checks,
        note=f"status={result.status}; bytes={result.bytes_read}",
    )


def add_screenshot(cwd: str | Path, recording_id: str, path: str | Path, *, note: str = "") -> BrowserRecording:
    root = Path(cwd).expanduser().resolve()
    artifact = artifact_studio.record_artifact(
        root,
        path,
        kind="screenshot",
        source="browser-recorder",
        provenance=f"browser recording {recording_id}",
        note=note or "browser screenshot",
    )
    return update_recording(root, recording_id, screenshot=artifact.rel_path.replace("\\", "/"), note=note)


def add_console_error(cwd: str | Path, recording_id: str, error: str) -> BrowserRecording:
    return update_recording(cwd, recording_id, console_error=error, status="failed")


def add_note(cwd: str | Path, recording_id: str, note: str) -> BrowserRecording:
    return update_recording(cwd, recording_id, note=note)


def update_recording(
    cwd: str | Path,
    recording_id: str,
    *,
    status: str = "",
    title: str = "",
    screenshot: str = "",
    console_error: str = "",
    note: str = "",
    checks: list[str] | None = None,
) -> BrowserRecording:
    root = Path(cwd).expanduser().resolve()
    rows = []
    updated: BrowserRecording | None = None
    now = _now()
    for recording in list_recordings(root, include_all=True):
        if recording.recording_id != recording_id:
            rows.append(recording)
            continue
        updated = replace(
            recording,
            status=_status(status or recording.status),
            title=_clean(title or recording.title, 180),
            screenshots=_dedupe([*(recording.screenshots or []), screenshot]),
            console_errors=_dedupe([*(recording.console_errors or []), _clean(console_error, 1_000)]),
            notes=_dedupe([*(recording.notes or []), _clean(note, 1_000)]),
            checks=_dedupe([*(recording.checks or []), *(checks or [])]),
            updated_at=now,
        )
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown browser recording: {recording_id}")
    _write(root, rows)
    return updated


def list_recordings(cwd: str | Path, *, include_all: bool = False, limit: int = 50) -> list[BrowserRecording]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status in {"running", "verified", "failed"}]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_recordings(cwd, include_all=True, limit=30)
    return {
        "total": len(rows),
        "running": sum(1 for row in rows if row.status == "running"),
        "failed": sum(1 for row in rows if row.status == "failed"),
        "recordings": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_recordings(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Browser Visual Recordings"]
    for row in rows:
        lines.append(
            f"- {row.status} {row.url}; title={row.title or 'unknown'}; screenshots={len(row.screenshots)}; console_errors={len(row.console_errors)}"
        )
    return "\n".join(lines)


def _read(cwd: str | Path) -> list[BrowserRecording]:
    path = recordings_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("recordings", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                BrowserRecording(
                    recording_id=str(item.get("recording_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    url=str(item.get("url") or ""),
                    title=str(item.get("title") or ""),
                    status=_status(str(item.get("status") or "running")),
                    mission_id=str(item.get("mission_id") or ""),
                    thread_id=str(item.get("thread_id") or ""),
                    screenshots=[str(value) for value in item.get("screenshots", []) if str(value).strip()],
                    console_errors=[str(value) for value in item.get("console_errors", []) if str(value).strip()],
                    notes=[str(value) for value in item.get("notes", []) if str(value).strip()],
                    checks=[str(value) for value in item.get("checks", []) if str(value).strip()],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.recording_id and row.cwd]


def _write(cwd: str | Path, rows: list[BrowserRecording]) -> None:
    path = recordings_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "recordings": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _thread(root: Path, *, mission_id: str = "", thread_id: str = ""):
    threads = work_threads.list_threads(root, include_all=True)
    if thread_id:
        return next((thread for thread in threads if thread.thread_id == thread_id), None)
    if mission_id:
        return next((thread for thread in threads if thread.goal_id == mission_id), None)
    return threads[0] if threads else None


def _status(value: str) -> str:
    clean = str(value or "running").strip().lower()
    return clean if clean in {"running", "verified", "failed", "archived"} else "running"


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value, 1_000)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
