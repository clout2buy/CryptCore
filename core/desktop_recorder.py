"""Durable recorder for visual desktop operation."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import artifact_studio, desktop_operator, session, settings, work_threads


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DesktopActionLog:
    action: str
    target: str = ""
    narration: str = ""
    requires_approval: bool = False
    approved: bool = False
    at: int = 0


@dataclass(frozen=True)
class DesktopRecording:
    recording_id: str
    cwd: str
    title: str
    mode: str
    status: str = "planned"
    mission_id: str = ""
    thread_id: str = ""
    approval_required: bool = False
    actions: list[DesktopActionLog] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "actions": [asdict(action) for action in self.actions],
        }


def recordings_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "desktop" / "recordings.json"


def create_from_job(
    cwd: str | Path,
    title: str,
    job: desktop_operator.DesktopJob,
    *,
    mission_id: str = "",
    thread_id: str = "",
) -> DesktopRecording:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    thread = _thread(root, mission_id=mission_id, thread_id=thread_id)
    recording = DesktopRecording(
        recording_id="desktop_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        title=_clean(title, 160) or "Desktop operation",
        mode=job.mode,
        mission_id=mission_id or (thread.goal_id if thread else ""),
        thread_id=thread_id or (thread.thread_id if thread else ""),
        approval_required=job.approval_required,
        actions=[
            DesktopActionLog(
                action=step.action,
                target=step.target,
                narration=step.narration,
                requires_approval=step.requires_approval,
                at=now,
            )
            for step in job.steps
        ],
        safety_notes=[job.reason, "Sensitive actions must remain approval-gated."] if job.approval_required else [job.reason],
        created_at=now,
        updated_at=now,
    )
    rows = list_recordings(root, include_all=True)
    rows.insert(0, recording)
    _write(root, rows)
    return recording


def create_from_prompt(cwd: str | Path, text: str) -> DesktopRecording:
    return create_from_job(cwd, text, desktop_operator.plan(text))


def approve_action(cwd: str | Path, recording_id: str, action: str) -> DesktopRecording:
    rows = []
    updated: DesktopRecording | None = None
    now = _now()
    for recording in list_recordings(cwd, include_all=True):
        if recording.recording_id != recording_id:
            rows.append(recording)
            continue
        actions = [
            replace(item, approved=True, at=now)
            if item.action == action and item.requires_approval
            else item
            for item in recording.actions
        ]
        updated = replace(recording, actions=actions, updated_at=now)
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown desktop recording: {recording_id}")
    _write(cwd, rows)
    return updated


def add_screenshot(cwd: str | Path, recording_id: str, path: str | Path, *, note: str = "") -> DesktopRecording:
    root = Path(cwd).expanduser().resolve()
    artifact = artifact_studio.record_artifact(
        root,
        path,
        kind="screenshot",
        source="desktop-recorder",
        provenance=f"desktop recording {recording_id}",
        note=note or "desktop screenshot",
    )
    return update_recording(root, recording_id, screenshot=artifact.rel_path.replace("\\", "/"), note=note)


def update_recording(
    cwd: str | Path,
    recording_id: str,
    *,
    status: str = "",
    screenshot: str = "",
    note: str = "",
) -> DesktopRecording:
    rows = []
    updated: DesktopRecording | None = None
    now = _now()
    for recording in list_recordings(cwd, include_all=True):
        if recording.recording_id != recording_id:
            rows.append(recording)
            continue
        updated = replace(
            recording,
            status=_status(status or recording.status),
            screenshots=_dedupe([*recording.screenshots, screenshot]),
            safety_notes=_dedupe([*recording.safety_notes, note]),
            updated_at=now,
        )
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown desktop recording: {recording_id}")
    _write(cwd, rows)
    return updated


def list_recordings(cwd: str | Path, *, include_all: bool = False, limit: int = 50) -> list[DesktopRecording]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status in {"planned", "running", "blocked", "done", "failed"}]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_recordings(cwd, include_all=True, limit=30)
    return {
        "total": len(rows),
        "approvalRequired": sum(1 for row in rows if row.approval_required),
        "recordings": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_recordings(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Desktop Operation Recordings"]
    for row in rows:
        lines.append(
            f"- {row.status} {row.title}; mode={row.mode}; actions={len(row.actions)}; approval_required={row.approval_required}; screenshots={len(row.screenshots)}"
        )
    return "\n".join(lines)


def _read(cwd: str | Path) -> list[DesktopRecording]:
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
            rows.append(_recording_from_dict(item))
        except Exception:
            continue
    return [row for row in rows if row.recording_id and row.cwd]


def _write(cwd: str | Path, rows: list[DesktopRecording]) -> None:
    path = recordings_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "recordings": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _recording_from_dict(item: dict[str, Any]) -> DesktopRecording:
    actions = []
    for raw in item.get("actions", []):
        if isinstance(raw, dict):
            actions.append(
                DesktopActionLog(
                    action=str(raw.get("action") or ""),
                    target=str(raw.get("target") or ""),
                    narration=str(raw.get("narration") or ""),
                    requires_approval=bool(raw.get("requires_approval")),
                    approved=bool(raw.get("approved")),
                    at=int(raw.get("at") or 0),
                )
            )
    return DesktopRecording(
        recording_id=str(item.get("recording_id") or ""),
        cwd=str(item.get("cwd") or ""),
        title=str(item.get("title") or ""),
        mode=str(item.get("mode") or "visual-desktop"),
        status=_status(str(item.get("status") or "planned")),
        mission_id=str(item.get("mission_id") or ""),
        thread_id=str(item.get("thread_id") or ""),
        approval_required=bool(item.get("approval_required")),
        actions=actions,
        screenshots=[str(value) for value in item.get("screenshots", []) if str(value).strip()],
        safety_notes=[str(value) for value in item.get("safety_notes", []) if str(value).strip()],
        created_at=int(item.get("created_at") or 0),
        updated_at=int(item.get("updated_at") or 0),
    )


def _thread(root: Path, *, mission_id: str = "", thread_id: str = ""):
    threads = work_threads.list_threads(root, include_all=True)
    if thread_id:
        return next((thread for thread in threads if thread.thread_id == thread_id), None)
    if mission_id:
        return next((thread for thread in threads if thread.goal_id == mission_id), None)
    return threads[0] if threads else None


def _status(value: str) -> str:
    clean = str(value or "planned").strip().lower()
    return clean if clean in {"planned", "running", "blocked", "done", "failed", "archived"} else "planned"


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
