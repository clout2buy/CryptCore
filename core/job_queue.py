"""Persistent background job queue state."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import session, settings


SCHEMA_VERSION = 1
STATUSES = {"queued", "running", "succeeded", "failed", "cancelled", "interrupted"}


@dataclass(frozen=True)
class QueueLog:
    at: int
    level: str
    text: str


@dataclass(frozen=True)
class QueueJob:
    job_id: str
    cwd: str
    title: str
    kind: str = "task"
    prompt: str = ""
    status: str = "queued"
    priority: int = 3
    attempts: int = 0
    cancel_requested: bool = False
    result: str = ""
    logs: list[QueueLog] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0
    started_at: int = 0
    finished_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "logs": [asdict(log) for log in self.logs]}


def queue_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "jobs" / "queue.json"


def enqueue(
    cwd: str | Path,
    title: str,
    *,
    kind: str = "task",
    prompt: str = "",
    priority: int = 3,
) -> QueueJob:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    job = QueueJob(
        job_id="job_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        title=_clean(title, 160) or "Background job",
        kind=_clean(kind, 60) or "task",
        prompt=_clean(prompt, 2_000),
        priority=max(1, min(5, int(priority or 3))),
        logs=[QueueLog(now, "info", "queued")],
        created_at=now,
        updated_at=now,
    )
    rows = list_jobs(root, include_all=True)
    rows.insert(0, job)
    _write(root, rows)
    return job


def start(cwd: str | Path, job_id: str) -> QueueJob:
    return _mutate(cwd, job_id, status="running", attempts_delta=1, started=True, log=("info", "started"))


def append_log(cwd: str | Path, job_id: str, text: str, *, level: str = "info") -> QueueJob:
    return _mutate(cwd, job_id, log=(level, text))


def complete(cwd: str | Path, job_id: str, *, result: str = "") -> QueueJob:
    return _mutate(cwd, job_id, status="succeeded", result=result, finished=True, log=("info", result or "completed"))


def fail(cwd: str | Path, job_id: str, *, error: str) -> QueueJob:
    return _mutate(cwd, job_id, status="failed", result=error, finished=True, log=("error", error))


def cancel(cwd: str | Path, job_id: str, *, reason: str = "") -> QueueJob:
    return _mutate(cwd, job_id, status="cancelled", cancel_requested=True, finished=True, log=("warn", reason or "cancelled"))


def recover(cwd: str | Path) -> list[QueueJob]:
    root = Path(cwd).expanduser().resolve()
    rows = []
    recovered = []
    now = _now()
    for job in list_jobs(root, include_all=True):
        if job.status == "running":
            updated = replace(
                job,
                status="interrupted",
                updated_at=now,
                finished_at=now,
                logs=_trim_logs([*job.logs, QueueLog(now, "warn", "marked interrupted during queue recovery")]),
            )
            rows.append(updated)
            recovered.append(updated)
        else:
            rows.append(job)
    if recovered:
        _write(root, rows)
    return recovered


def list_jobs(cwd: str | Path, *, include_all: bool = False, limit: int = 80) -> list[QueueJob]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status in {"queued", "running", "interrupted"}]
    rows.sort(key=lambda row: (row.status == "running", row.priority, row.updated_at), reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_jobs(cwd, include_all=True, limit=40)
    return {
        "total": len(rows),
        "queued": sum(1 for row in rows if row.status == "queued"),
        "running": sum(1 for row in rows if row.status == "running"),
        "failed": sum(1 for row in rows if row.status == "failed"),
        "cancelled": sum(1 for row in rows if row.status == "cancelled"),
        "interrupted": sum(1 for row in rows if row.status == "interrupted"),
        "jobs": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 6) -> str:
    rows = list_jobs(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Job Queue"]
    for row in rows:
        last = row.logs[-1].text if row.logs else row.result
        lines.append(f"- {row.status} {row.title}; attempts={row.attempts}; cancel={row.cancel_requested}; last={last}")
    return "\n".join(lines)


def _mutate(
    cwd: str | Path,
    job_id: str,
    *,
    status: str | None = None,
    result: str = "",
    attempts_delta: int = 0,
    cancel_requested: bool | None = None,
    started: bool = False,
    finished: bool = False,
    log: tuple[str, str] | None = None,
) -> QueueJob:
    root = Path(cwd).expanduser().resolve()
    rows = []
    updated: QueueJob | None = None
    now = _now()
    for job in list_jobs(root, include_all=True):
        if job.job_id != job_id:
            rows.append(job)
            continue
        logs = list(job.logs)
        if log and log[1]:
            logs.append(QueueLog(now, _clean(log[0], 20) or "info", _clean(log[1], 1_000)))
        updated = replace(
            job,
            status=_status(status or job.status),
            result=_clean(result or job.result, 2_000),
            attempts=job.attempts + int(attempts_delta or 0),
            cancel_requested=job.cancel_requested if cancel_requested is None else bool(cancel_requested),
            logs=_trim_logs(logs),
            updated_at=now,
            started_at=now if started and not job.started_at else job.started_at,
            finished_at=now if finished else job.finished_at,
        )
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown job: {job_id}")
    _write(root, rows)
    return updated


def _read(cwd: str | Path) -> list[QueueJob]:
    path = queue_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("jobs", []):
        if not isinstance(item, dict):
            continue
        try:
            logs = [
                QueueLog(at=int(raw.get("at") or 0), level=str(raw.get("level") or "info"), text=str(raw.get("text") or ""))
                for raw in item.get("logs", [])
                if isinstance(raw, dict)
            ]
            rows.append(
                QueueJob(
                    job_id=str(item.get("job_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    title=str(item.get("title") or ""),
                    kind=str(item.get("kind") or "task"),
                    prompt=str(item.get("prompt") or ""),
                    status=_status(str(item.get("status") or "queued")),
                    priority=int(item.get("priority") or 3),
                    attempts=int(item.get("attempts") or 0),
                    cancel_requested=bool(item.get("cancel_requested")),
                    result=str(item.get("result") or ""),
                    logs=logs,
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                    started_at=int(item.get("started_at") or 0),
                    finished_at=int(item.get("finished_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.job_id and row.cwd]


def _write(cwd: str | Path, rows: list[QueueJob]) -> None:
    path = queue_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "jobs": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _trim_logs(logs: list[QueueLog]) -> list[QueueLog]:
    return logs[-30:]


def _status(value: str) -> str:
    clean = str(value or "queued").strip().lower()
    return clean if clean in STATUSES else "queued"


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
