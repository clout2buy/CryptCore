"""Local autonomous scheduler for safe mission follow-ups."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import evidence, goals, settings, work_threads


SCHEMA_VERSION = 1
ACTIVE_STATUSES = {"active", "paused", "completed", "cancelled"}


@dataclass(frozen=True)
class ScheduledJob:
    job_id: str
    cwd: str
    title: str
    prompt: str = ""
    kind: str = "mission-check"
    status: str = "active"
    cadence: str = ""
    due_at: int = 0
    priority: int = 3
    goal_id: str = ""
    thread_id: str = ""
    escalation_rules: list[str] = field(default_factory=list)
    last_result: str = ""
    last_run_at: int = 0
    run_count: int = 0
    missed_runs: int = 0
    created_at: int = 0
    updated_at: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SchedulerRun:
    run_id: str
    cwd: str
    created_at: int
    checked: int = 0
    ran: int = 0
    results: list[str] = field(default_factory=list)


def schedules_path() -> Path:
    return settings.APP_DIR / "schedules" / "jobs.json"


def schedule_followup(
    cwd: str | Path,
    title: str,
    *,
    prompt: str = "",
    due_at: int = 0,
    cadence: str = "",
    goal_id: str = "",
    thread_id: str = "",
    kind: str = "mission-check",
    priority: int = 3,
    escalation_rules: list[str] | None = None,
) -> ScheduledJob:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    job = ScheduledJob(
        job_id="sched_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        title=_clean(title),
        prompt=_clean(prompt, 2_000),
        kind=_clean(kind, 80) or "mission-check",
        status="active",
        cadence=_clean(cadence, 80),
        due_at=int(due_at or _next_due(cadence, now) or now),
        priority=max(1, min(5, int(priority or 3))),
        goal_id=_clean(goal_id, 80),
        thread_id=_clean(thread_id, 80),
        escalation_rules=_dedupe(escalation_rules or _default_escalation_rules(cadence)),
        created_at=now,
        updated_at=now,
        history=[_history("created", "scheduled follow-up created", now)],
    )
    jobs = list_jobs(include_all=True)
    jobs.append(job)
    _write(jobs)
    return job


def ensure_goal_schedule(goal: goals.Goal) -> ScheduledJob | None:
    if not goal.cadence or goal.status != "active":
        return None
    root = Path(goal.workspace or ".").expanduser().resolve()
    now = _now()
    jobs = list_jobs(root, include_all=True)
    existing = next((job for job in jobs if job.goal_id == goal.goal_id), None)
    thread = next((item for item in work_threads.list_threads(root, include_all=True) if item.goal_id == goal.goal_id), None)
    due_at = int(goal.next_review_at or _next_due(goal.cadence, now) or now)
    if existing:
        updated = _replace_job(
            existing.job_id,
            cwd=root,
            title=goal.title,
            prompt=goal.description,
        cadence=goal.cadence,
        due_at=due_at,
        thread_id=thread.thread_id if thread else existing.thread_id,
        priority=goal.priority,
        status="active",
        note="synced from goal cadence",
        )
        return updated
    return schedule_followup(
        root,
        goal.title,
        prompt=goal.description,
        due_at=due_at,
        cadence=goal.cadence,
        goal_id=goal.goal_id,
        thread_id=thread.thread_id if thread else "",
        kind="goal-review",
        priority=goal.priority,
        escalation_rules=["escalate if review is missed by 1 day", "mark blocker if goal has no next action"],
    )


def sync_goal_schedules(cwd: str | Path) -> list[ScheduledJob]:
    root = Path(cwd).expanduser().resolve()
    synced: list[ScheduledJob] = []
    for goal in goals.list_goals(root):
        job = ensure_goal_schedule(goal)
        if job is not None:
            synced.append(job)
    return synced


def list_jobs(cwd: str | Path | None = None, *, include_all: bool = False) -> list[ScheduledJob]:
    root = str(Path(cwd).expanduser().resolve()) if cwd else ""
    jobs = _read()
    if not include_all:
        jobs = [job for job in jobs if job.status == "active"]
    if root:
        jobs = [job for job in jobs if job.cwd == root]
    jobs.sort(key=lambda job: (job.due_at or 0, job.updated_at), reverse=False)
    return jobs


def due_jobs(cwd: str | Path, *, now: int | None = None) -> list[ScheduledJob]:
    root = Path(cwd).expanduser().resolve()
    sync_goal_schedules(root)
    current = _now() if now is None else int(now)
    return [
        job for job in list_jobs(root)
        if job.status == "active" and job.due_at and job.due_at <= current
    ]


def pause_job(job_id: str, cwd: str | Path, *, reason: str = "") -> ScheduledJob:
    return _replace_job(
        job_id,
        cwd=cwd,
        status="paused",
        note=f"paused schedule: {_clean(reason) or 'no reason provided'}",
    )


def resume_job(job_id: str, cwd: str | Path, *, due_at: int = 0) -> ScheduledJob:
    values: dict[str, Any] = {"status": "active"}
    if due_at:
        values["due_at"] = int(due_at)
    return _replace_job(job_id, cwd=cwd, note="resumed schedule", **values)


def snapshot(cwd: str | Path) -> dict[str, Any]:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    jobs = list_jobs(root, include_all=True)
    active = [job for job in jobs if job.status == "active"]
    due = [job for job in active if job.due_at and job.due_at <= now]
    paused = [job for job in jobs if job.status == "paused"]
    overdue = [job for job in due if _is_overdue(job, now)]
    return {
        "total": len(jobs),
        "active": len(active),
        "paused": len(paused),
        "due": len(due),
        "overdue": len(overdue),
        "nextDueAt": min([job.due_at for job in active if job.due_at] or [0]),
        "jobs": [asdict(job) for job in jobs[:30]],
    }


def run_due(cwd: str | Path, *, now: int | None = None, limit: int = 10) -> SchedulerRun:
    root = Path(cwd).expanduser().resolve()
    current = _now() if now is None else int(now)
    due = due_jobs(root, now=current)[: max(1, limit)]
    results: list[str] = []
    for job in due:
        result = _run_job(root, job, now=current)
        results.append(result.last_result)
    return SchedulerRun(
        run_id="run_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        created_at=current,
        checked=len(list_jobs(root)),
        ran=len(due),
        results=results,
    )


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    jobs = list_jobs(cwd)[: max(1, limit)]
    if not jobs:
        return ""
    lines = ["# Scheduler"]
    for job in jobs:
        due = time.strftime("%Y-%m-%d %H:%M", time.localtime(job.due_at)) if job.due_at else "unscheduled"
        escalation = f" | escalation: {', '.join(job.escalation_rules[:2])}" if job.escalation_rules else ""
        lines.append(
            f"- {job.kind} P{job.priority} {job.status} {job.title} | "
            f"due: {due} | cadence: {job.cadence or 'once'}{escalation}"
        )
    return "\n".join(lines)


def _run_job(root: Path, job: ScheduledJob, *, now: int) -> ScheduledJob:
    summary = f"Scheduled {job.kind} reviewed: {job.title}"
    escalation = _escalation_note(job, now)
    if escalation:
        summary += f" | escalation: {escalation}"
    evidence.record("schedule", "scheduler", summary, task_id=job.thread_id or job.job_id)
    if job.goal_id:
        try:
            goals.update_goal(
                job.goal_id,
                last_result=summary,
                next_review_at=_next_due(job.cadence, now) if job.cadence else 0,
            )
        except Exception:
            pass
    if job.thread_id:
        try:
            work_threads.update_thread(
                job.thread_id,
                last_note=summary,
                bump_due=bool(job.cadence),
                source="scheduler",
            )
        except Exception:
            pass
    next_due = _next_due(job.cadence, now) if job.cadence else 0
    status = "active" if next_due else "completed"
    return _replace_job(
        job.job_id,
        cwd=root,
        status=status,
        due_at=next_due,
        last_result=summary,
        last_run_at=now,
        run_count=job.run_count + 1,
        missed_runs=job.missed_runs + (1 if escalation else 0),
        note=summary,
    )


def _replace_job(job_id: str, *, cwd: str | Path, note: str = "", **values: Any) -> ScheduledJob:
    root = Path(cwd).expanduser().resolve()
    jobs = list_jobs(include_all=True)
    now = _now()
    out: list[ScheduledJob] = []
    updated: ScheduledJob | None = None
    for job in jobs:
        if job.job_id != job_id:
            out.append(job)
            continue
        data = asdict(job)
        for key in ("title", "prompt", "kind", "cadence", "goal_id", "thread_id", "last_result"):
            if key in values and values[key] is not None:
                data[key] = _clean(str(values[key]), 2_000)
        if "escalation_rules" in values and values["escalation_rules"] is not None:
            raw_rules = values["escalation_rules"]
            if isinstance(raw_rules, list):
                data["escalation_rules"] = _dedupe([_clean(str(rule), 200) for rule in raw_rules])
        for key in ("priority", "last_run_at", "missed_runs"):
            if key in values and values[key] is not None:
                data[key] = int(values[key])
        if "status" in values and values["status"] is not None:
            status = str(values["status"]).strip().lower()
            if status not in ACTIVE_STATUSES:
                raise ValueError(f"unknown schedule status: {status}")
            data["status"] = status
        if "due_at" in values and values["due_at"] is not None:
            data["due_at"] = int(values["due_at"])
        if "run_count" in values and values["run_count"] is not None:
            data["run_count"] = int(values["run_count"])
        data["cwd"] = str(root)
        data["updated_at"] = now
        if note:
            data["history"] = [_history("scheduler", note, now), *job.history[:20]]
        updated = ScheduledJob(**data)
        out.append(updated)
    if updated is None:
        raise KeyError(f"schedule not found: {job_id}")
    _write(out)
    return updated


def _read() -> list[ScheduledJob]:
    path = schedules_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[ScheduledJob] = []
    for item in data.get("jobs", []):
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                ScheduledJob(
                    job_id=str(item.get("job_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    title=str(item.get("title") or ""),
                    prompt=str(item.get("prompt") or ""),
                    kind=str(item.get("kind") or "mission-check"),
                    status=str(item.get("status") or "active"),
                    cadence=str(item.get("cadence") or ""),
                    due_at=int(item.get("due_at") or 0),
                    priority=int(item.get("priority") or 3),
                    goal_id=str(item.get("goal_id") or ""),
                    thread_id=str(item.get("thread_id") or ""),
                    escalation_rules=[str(rule) for rule in item.get("escalation_rules", []) if str(rule)],
                    last_result=str(item.get("last_result") or ""),
                    last_run_at=int(item.get("last_run_at") or 0),
                    run_count=int(item.get("run_count") or 0),
                    missed_runs=int(item.get("missed_runs") or 0),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                    history=[item for item in item.get("history", []) if isinstance(item, dict)],
                )
            )
        except Exception:
            continue
    return [job for job in out if job.job_id and job.title]


def _write(jobs: list[ScheduledJob]) -> None:
    path = schedules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "jobs": [asdict(job) for job in jobs]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _next_due(cadence: str, now: int) -> int:
    value = str(cadence or "").strip().lower()
    if value in {"hourly", "hour"}:
        return now + 60 * 60
    if value in {"daily", "day"}:
        return now + 24 * 60 * 60
    if value in {"weekly", "week"}:
        return now + 7 * 24 * 60 * 60
    if value in {"monthly", "month"}:
        return now + 30 * 24 * 60 * 60
    return 0


def _is_overdue(job: ScheduledJob, now: int) -> bool:
    return bool(job.due_at and now - job.due_at >= _overdue_seconds(job))


def _overdue_seconds(job: ScheduledJob) -> int:
    if job.cadence in {"hourly", "hour"}:
        return 2 * 60 * 60
    if job.cadence in {"weekly", "week"}:
        return 2 * 24 * 60 * 60
    if job.cadence in {"monthly", "month"}:
        return 5 * 24 * 60 * 60
    return 24 * 60 * 60


def _escalation_note(job: ScheduledJob, now: int) -> str:
    if not _is_overdue(job, now):
        return ""
    rules = ", ".join(job.escalation_rules[:2]) or "schedule is overdue"
    return f"overdue by {max(0, now - job.due_at)}s; {rules}"


def _default_escalation_rules(cadence: str) -> list[str]:
    if cadence:
        return ["escalate if missed past grace window", "preserve blocker and next action in mission history"]
    return ["complete after one run", "record result evidence"]


def _history(source: str, text: str, now: int) -> dict[str, Any]:
    return {"source": source, "text": _clean(text, 500), "at": now}


def _clean(value: str, limit: int = 500) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(str(value or ""), 200)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def stable_job_id(goal_id: str) -> str:
    return "sched_" + hashlib.sha1(str(goal_id).encode("utf-8", errors="replace")).hexdigest()[:10]


def _now() -> int:
    return int(time.time())
