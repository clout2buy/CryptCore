"""Durable mission workers with explicit external-action gates."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import connector_readiness, job_queue, session, settings, work_threads


SCHEMA_VERSION = 1
STATUSES = {"active", "blocked", "paused", "completed", "cancelled"}


@dataclass(frozen=True)
class WorkerLog:
    at: int
    level: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MissionWorker:
    worker_id: str
    cwd: str
    title: str
    prompt: str
    thread_id: str = ""
    goal_id: str = ""
    status: str = "active"
    cadence_seconds: int = 900
    cycle_count: int = 0
    next_run_at: int = 0
    last_run_at: int = 0
    external_gate_required: bool = False
    external_approved: bool = False
    gate_reason: str = ""
    last_job_id: str = ""
    logs: list[WorkerLog] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["logs"] = [log.to_dict() for log in self.logs]
        return data


def workers_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "mission_workers" / "workers.json"


def create_worker(
    cwd: str | Path,
    title: str,
    *,
    prompt: str = "",
    thread_id: str = "",
    goal_id: str = "",
    cadence_seconds: int = 900,
    external_approved: bool = False,
) -> MissionWorker:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    decision = connector_readiness.assess(root, f"{title} {prompt}")
    gated = bool(decision.get("approvalRequired") and decision.get("external"))
    worker = MissionWorker(
        worker_id="worker_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        title=_clean(title, 160) or "Mission worker",
        prompt=_clean(prompt, 2_000),
        thread_id=_clean(thread_id, 100),
        goal_id=_clean(goal_id, 100),
        status="blocked" if gated and not external_approved else "active",
        cadence_seconds=max(60, int(cadence_seconds or 900)),
        next_run_at=now,
        external_gate_required=gated,
        external_approved=bool(external_approved),
        gate_reason=str(decision.get("safeNextStep") or "") if gated else "",
        logs=[
            WorkerLog(now, "warn" if gated and not external_approved else "info", "created; external approval required" if gated and not external_approved else "created"),
        ],
        created_at=now,
        updated_at=now,
    )
    rows = list_workers(root, include_all=True)
    rows.insert(0, worker)
    _write(root, rows)
    return worker


def ensure_for_thread(cwd: str | Path, thread: work_threads.WorkThread, *, prompt: str = "") -> MissionWorker:
    root = Path(cwd).expanduser().resolve()
    existing = next((worker for worker in list_workers(root, include_all=True) if worker.thread_id == thread.thread_id), None)
    if existing:
        return existing
    return create_worker(
        root,
        thread.title,
        prompt=prompt or thread.next_action or thread.title,
        thread_id=thread.thread_id,
        goal_id=thread.goal_id,
        cadence_seconds=900,
    )


def approve_external(cwd: str | Path, worker_id: str, *, note: str = "") -> MissionWorker:
    return _mutate(
        cwd,
        worker_id,
        status="active",
        external_approved=True,
        gate_reason="",
        log=("approval", _clean(note, 300) or "external gate approved by user"),
    )


def pause_worker(cwd: str | Path, worker_id: str, *, reason: str = "") -> MissionWorker:
    return _mutate(cwd, worker_id, status="paused", log=("info", _clean(reason, 300) or "paused"))


def complete_worker(cwd: str | Path, worker_id: str, *, result: str = "") -> MissionWorker:
    return _mutate(cwd, worker_id, status="completed", log=("success", _clean(result, 500) or "completed"))


def run_cycle(cwd: str | Path, worker_id: str, *, now: int | None = None) -> MissionWorker:
    root = Path(cwd).expanduser().resolve()
    current = int(now or _now())
    worker = _get(root, worker_id)
    if worker.status in {"paused", "completed", "cancelled"}:
        return _mutate(root, worker_id, log=("info", f"cycle skipped: {worker.status}"))
    decision = connector_readiness.assess(root, f"{worker.title} {worker.prompt}")
    gate_required = bool(decision.get("approvalRequired") and decision.get("external"))
    if gate_required and not worker.external_approved:
        return _mutate(
            root,
            worker_id,
            status="blocked",
            external_gate_required=True,
            gate_reason=str(decision.get("safeNextStep") or "external action requires explicit approval"),
            log=("warn", "blocked before external action; approval required"),
        )
    job = job_queue.enqueue(
        root,
        f"Mission worker: {worker.title}",
        kind="mission-worker",
        prompt=_cycle_prompt(worker, decision),
        priority=worker_priority(worker),
    )
    return _mutate(
        root,
        worker_id,
        status="active",
        cycle_delta=1,
        last_run_at=current,
        next_run_at=current + worker.cadence_seconds,
        last_job_id=job.job_id,
        external_gate_required=gate_required,
        gate_reason="",
        log=("info", f"queued cycle {worker.cycle_count + 1}: {job.job_id}"),
    )


def run_due(cwd: str | Path, *, now: int | None = None, limit: int = 5) -> list[MissionWorker]:
    root = Path(cwd).expanduser().resolve()
    current = int(now or _now())
    due = [
        worker
        for worker in list_workers(root)
        if worker.status in {"active", "blocked"} and worker.next_run_at and worker.next_run_at <= current
    ]
    return [run_cycle(root, worker.worker_id, now=current) for worker in due[: max(1, limit)]]


def list_workers(cwd: str | Path, *, include_all: bool = False, limit: int = 80) -> list[MissionWorker]:
    rows = _read(cwd)
    if not include_all:
        rows = [worker for worker in rows if worker.status in {"active", "blocked", "paused"}]
    rows.sort(key=lambda worker: (worker.status == "blocked", worker.next_run_at or worker.updated_at), reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_workers(cwd, include_all=True, limit=40)
    return {
        "total": len(rows),
        "active": sum(1 for row in rows if row.status == "active"),
        "blocked": sum(1 for row in rows if row.status == "blocked"),
        "paused": sum(1 for row in rows if row.status == "paused"),
        "gated": sum(1 for row in rows if row.external_gate_required and not row.external_approved),
        "workers": [row.to_dict() for row in rows[:16]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 6) -> str:
    rows = list_workers(cwd)[: max(1, limit)]
    if not rows:
        return ""
    lines = ["# Long-Running Mission Workers"]
    for worker in rows:
        gate = f"; gate={worker.gate_reason}" if worker.status == "blocked" or worker.external_gate_required else ""
        lines.append(f"- {worker.status} {worker.title}; cycles={worker.cycle_count}; next={worker.next_run_at}{gate}")
    return "\n".join(lines)


def worker_priority(worker: MissionWorker) -> int:
    if worker.external_gate_required and not worker.external_approved:
        return 1
    if worker.status == "blocked":
        return 2
    return 3


def _cycle_prompt(worker: MissionWorker, decision: dict[str, Any]) -> str:
    lines = [
        f"Continue long-running mission worker: {worker.title}",
        worker.prompt,
        f"Thread: {worker.thread_id or 'none'} Goal: {worker.goal_id or 'none'}",
        "Persist findings, update mission state, and stop before any external send/post/payment/write.",
    ]
    if decision.get("connector"):
        lines.append(f"Connector: {decision.get('label')} status={decision.get('status')} next={decision.get('safeNextStep')}")
    return "\n".join(line for line in lines if line)


def _get(cwd: str | Path, worker_id: str) -> MissionWorker:
    worker = next((item for item in list_workers(cwd, include_all=True) if item.worker_id == worker_id), None)
    if worker is None:
        raise KeyError(f"unknown mission worker: {worker_id}")
    return worker


def _mutate(
    cwd: str | Path,
    worker_id: str,
    *,
    status: str | None = None,
    cycle_delta: int = 0,
    last_run_at: int | None = None,
    next_run_at: int | None = None,
    external_gate_required: bool | None = None,
    external_approved: bool | None = None,
    gate_reason: str | None = None,
    last_job_id: str | None = None,
    log: tuple[str, str] | None = None,
) -> MissionWorker:
    root = Path(cwd).expanduser().resolve()
    rows: list[MissionWorker] = []
    updated: MissionWorker | None = None
    now = _now()
    for worker in list_workers(root, include_all=True):
        if worker.worker_id != worker_id:
            rows.append(worker)
            continue
        logs = list(worker.logs)
        if log and log[1]:
            logs.insert(0, WorkerLog(now, _clean(log[0], 40) or "info", _clean(log[1], 800)))
        updated = replace(
            worker,
            status=_status(status or worker.status),
            cycle_count=worker.cycle_count + int(cycle_delta or 0),
            last_run_at=worker.last_run_at if last_run_at is None else int(last_run_at),
            next_run_at=worker.next_run_at if next_run_at is None else int(next_run_at),
            external_gate_required=worker.external_gate_required if external_gate_required is None else bool(external_gate_required),
            external_approved=worker.external_approved if external_approved is None else bool(external_approved),
            gate_reason=worker.gate_reason if gate_reason is None else _clean(gate_reason, 500),
            last_job_id=worker.last_job_id if last_job_id is None else _clean(last_job_id, 120),
            logs=logs[:30],
            updated_at=now,
        )
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown mission worker: {worker_id}")
    _write(root, rows)
    return updated


def _read(cwd: str | Path) -> list[MissionWorker]:
    path = workers_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    out: list[MissionWorker] = []
    for item in data.get("workers", []):
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                MissionWorker(
                    worker_id=str(item.get("worker_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    title=str(item.get("title") or ""),
                    prompt=str(item.get("prompt") or ""),
                    thread_id=str(item.get("thread_id") or ""),
                    goal_id=str(item.get("goal_id") or ""),
                    status=_status(str(item.get("status") or "active")),
                    cadence_seconds=max(60, int(item.get("cadence_seconds") or 900)),
                    cycle_count=int(item.get("cycle_count") or 0),
                    next_run_at=int(item.get("next_run_at") or 0),
                    last_run_at=int(item.get("last_run_at") or 0),
                    external_gate_required=bool(item.get("external_gate_required")),
                    external_approved=bool(item.get("external_approved")),
                    gate_reason=str(item.get("gate_reason") or ""),
                    last_job_id=str(item.get("last_job_id") or ""),
                    logs=[
                        WorkerLog(int(log.get("at") or 0), str(log.get("level") or "info"), str(log.get("text") or ""))
                        for log in item.get("logs", [])
                        if isinstance(log, dict)
                    ],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [item for item in out if item.worker_id and item.cwd]


def _write(cwd: str | Path, rows: list[MissionWorker]) -> None:
    path = workers_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "workers": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _status(value: str) -> str:
    clean = str(value or "active").strip().lower()
    return clean if clean in STATUSES else "active"


def _clean(value: object, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
