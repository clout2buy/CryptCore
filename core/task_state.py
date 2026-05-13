"""Durable task state and event logs for Crypt.

Each user prompt becomes a task. The task log is append-only JSONL so terminal,
daemon, desktop, and future gateway clients can all reconstruct what happened
without scraping chat text.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import redact, session


VALID_STATUSES = {
    "queued",
    "planning",
    "tool_calling",
    "waiting_approval",
    "editing",
    "verifying",
    "completed",
    "failed",
    "cancelled",
}


@dataclass(frozen=True)
class TaskInfo:
    task_id: str
    path: Path
    cwd: str = ""
    prompt: str = ""
    status: str = "queued"
    provider: str = ""
    model: str = ""
    session_id: str = ""
    created_at: int = 0
    updated_at: int = 0
    event_count: int = 0
    last_detail: str = ""


def start_task(
    prompt: str,
    *,
    cwd: str | Path,
    provider: str = "",
    model: str = "",
    session_id: str = "",
) -> TaskInfo:
    task_id = _new_task_id()
    now = _now()
    entry = {
        "type": "meta",
        "task_id": task_id,
        "cwd": str(Path(cwd).expanduser().resolve()),
        "prompt": redact.text(prompt)[:8000],
        "provider": provider,
        "model": model,
        "session_id": session_id,
        "status": "queued",
        "created_at": now,
        "ts": now,
    }
    _append(cwd, task_id, entry)
    set_status(cwd, task_id, "planning", "task accepted")
    return info(cwd, task_id)


def set_status(
    cwd: str | Path,
    task_id: str,
    status: str,
    detail: str = "",
    *,
    data: dict[str, Any] | None = None,
) -> None:
    normalized = str(status or "").strip().lower()
    if normalized not in VALID_STATUSES:
        raise ValueError(f"unknown task status: {status!r}")
    record_event(cwd, task_id, "status", detail or normalized, status=normalized, data=data)


def record_event(
    cwd: str | Path,
    task_id: str | None,
    event: str,
    detail: str = "",
    *,
    status: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    if not task_id:
        return
    entry = {
        "type": "event",
        "event": str(event or "event"),
        "detail": redact.text(str(detail or ""))[:4000],
        "ts": _now(),
    }
    if status:
        entry["status"] = status
    if data:
        entry["data"] = _jsonable(redact.content(data))
    _append(cwd, task_id, entry)


def task_path(cwd: str | Path, task_id: str) -> Path:
    return session.project_dir(cwd) / "tasks" / f"{task_id}.jsonl"


def read_events(cwd: str | Path, task_id: str) -> list[dict[str, Any]]:
    return _read_jsonl(task_path(cwd, task_id))


def info(cwd: str | Path, task_id: str) -> TaskInfo:
    return info_from_path(task_path(cwd, task_id))


def info_from_path(path: Path) -> TaskInfo:
    events = _read_jsonl(path)
    task_id = path.stem
    cwd = ""
    prompt = ""
    provider = ""
    model = ""
    session_id = ""
    status = "queued"
    created_at = 0
    updated_at = 0
    last_detail = ""
    for item in events:
        ts = int(item.get("ts") or item.get("created_at") or 0)
        if ts:
            updated_at = max(updated_at, ts)
        if item.get("type") == "meta":
            task_id = str(item.get("task_id") or task_id)
            cwd = str(item.get("cwd") or cwd)
            prompt = str(item.get("prompt") or prompt)
            provider = str(item.get("provider") or provider)
            model = str(item.get("model") or model)
            session_id = str(item.get("session_id") or session_id)
            status = str(item.get("status") or status)
            created_at = int(item.get("created_at") or item.get("ts") or created_at)
        elif item.get("type") == "event":
            status = str(item.get("status") or status)
            last_detail = str(item.get("detail") or last_detail)
    if not created_at:
        created_at = updated_at
    return TaskInfo(
        task_id=task_id,
        path=path,
        cwd=cwd,
        prompt=prompt,
        status=status,
        provider=provider,
        model=model,
        session_id=session_id,
        created_at=created_at,
        updated_at=updated_at,
        event_count=len(events),
        last_detail=last_detail,
    )


def list_tasks(cwd: str | Path | None = None, *, all_projects: bool = False, limit: int = 20) -> list[TaskInfo]:
    roots: list[Path]
    if all_projects:
        base = session.settings.APP_DIR / "projects"
        roots = [p / "tasks" for p in base.iterdir() if p.is_dir()] if base.exists() else []
    else:
        roots = [session.project_dir(cwd or Path.cwd()) / "tasks"]
    out: list[TaskInfo] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*.jsonl"):
            out.append(info_from_path(path))
    out.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
    return out[: max(1, limit)]


def format_task_list(cwd: str | Path, *, all_projects: bool = False, limit: int = 12) -> str:
    tasks = list_tasks(cwd, all_projects=all_projects, limit=limit)
    if not tasks:
        return "no tasks found"
    lines: list[str] = []
    for item in tasks:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.updated_at or item.created_at))
        prompt = " ".join(item.prompt.split())
        if len(prompt) > 80:
            prompt = prompt[:77].rstrip() + "..."
        lines.append(f"{item.task_id} {item.status} {when} - {prompt or item.last_detail}")
    return "\n".join(lines)


def format_task(cwd: str | Path, task_id: str, *, tail: int = 30) -> str:
    events = read_events(cwd, task_id)
    if not events:
        return f"task not found: {task_id}"
    info_obj = info(cwd, task_id)
    lines = [
        f"{info_obj.task_id} {info_obj.status}",
        f"cwd: {info_obj.cwd}",
        f"session: {info_obj.session_id or '(none)'}",
        f"model: {info_obj.provider}:{info_obj.model}".rstrip(":"),
        f"prompt: {info_obj.prompt}",
        "events:",
    ]
    for item in events[-max(1, tail):]:
        ts = int(item.get("ts") or item.get("created_at") or 0)
        when = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "--:--:--"
        if item.get("type") == "meta":
            lines.append(f"- {when} meta created")
            continue
        label = str(item.get("status") or item.get("event") or item.get("type") or "event")
        detail = str(item.get("detail") or "")
        lines.append(f"- {when} {label}: {detail}".rstrip())
    return "\n".join(lines)


def _append(cwd: str | Path, task_id: str, entry: dict[str, Any]) -> None:
    path = task_path(cwd, task_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        session.settings.restrict_file_permissions(path)
    except OSError:
        return


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    out.append(item)
    except OSError:
        return []
    return out


def _new_task_id() -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return f"task_{stamp}_{uuid.uuid4().hex[:8]}"


def _now() -> int:
    return int(time.time())


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return str(value)
