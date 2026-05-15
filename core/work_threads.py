"""Autonomous work-thread state for durable missions.

Goals describe outcomes. Work threads keep the operational state Crypt needs to
continue without making the user manage a project board by hand.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import goals, redact, settings


SCHEMA_VERSION = 1
THREAD_STATUSES = {"active", "blocked", "waiting", "paused", "completed", "cancelled"}
APPROVAL_TERMS = {
    "email",
    "reddit",
    "post",
    "publish",
    "message",
    "dm",
    "buy",
    "purchase",
    "spend",
    "payment",
    "credit card",
    "login",
    "password",
    "credential",
    "account",
    "domain",
}


@dataclass(frozen=True)
class WorkThread:
    thread_id: str
    goal_id: str
    title: str
    state: str = "active"
    workspace: str = ""
    priority: int = 3
    next_action: str = ""
    blockers: list[str] = field(default_factory=list)
    due_at: int = 0
    cadence: str = ""
    tags: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0


@dataclass(frozen=True)
class ThreadStatus:
    path: Path
    active: int = 0
    blocked: int = 0
    waiting: int = 0
    due: int = 0


def threads_dir() -> Path:
    return settings.APP_DIR / "work_threads"


def threads_path() -> Path:
    return threads_dir() / "threads.json"


def ensure_for_goal(goal: goals.Goal, *, prompt_text: str = "", source: str = "mission-router") -> WorkThread:
    """Create or update the thread that owns a durable goal."""
    threads = list_threads(include_all=True)
    existing = next((thread for thread in threads if thread.goal_id == goal.goal_id), None)
    now = _now()
    blockers = _blockers(f"{prompt_text} {goal.description} {goal.title}")
    state = "blocked" if blockers else "active"
    next_action = _next_action(goal, prompt_text)
    if existing:
        data = asdict(existing)
        changed = False
        if goal.title and goal.title != existing.title:
            data["title"] = goal.title
            changed = True
        if next_action and next_action != existing.next_action:
            data["next_action"] = next_action
            changed = True
        merged_blockers = _dedupe([*existing.blockers, *blockers])
        if merged_blockers != existing.blockers:
            data["blockers"] = merged_blockers
            data["state"] = "blocked" if merged_blockers else existing.state
            changed = True
        due_at = _due_at(goal, now)
        if due_at and due_at != existing.due_at:
            data["due_at"] = due_at
            changed = True
        if changed:
            data["updated_at"] = now
            data["history"] = _trim_history(
                [
                    _history(source, "thread refreshed from chat and mission state", now),
                    *existing.history,
                ]
            )
            updated = WorkThread(**data)
            _replace_thread(updated, threads)
            return updated
        return existing

    thread = WorkThread(
        thread_id=f"thread_{uuid.uuid4().hex[:10]}",
        goal_id=goal.goal_id,
        title=goal.title,
        state=state,
        workspace=goal.workspace,
        priority=goal.priority,
        next_action=next_action,
        blockers=blockers,
        due_at=_due_at(goal, now),
        cadence=goal.cadence,
        tags=_dedupe(["auto", "mission", *goal.tags]),
        history=[_history(source, "thread created automatically from chat", now)],
        created_at=now,
        updated_at=now,
    )
    threads.append(thread)
    _write(threads)
    return thread


def list_threads(
    workspace: str | Path | None = None,
    *,
    state: str = "",
    include_all: bool = False,
) -> list[WorkThread]:
    workspace_text = str(Path(workspace).expanduser().resolve()) if workspace else ""
    threads = _read()
    if not include_all:
        threads = [thread for thread in threads if thread.state not in {"completed", "cancelled"}]
    if state:
        threads = [thread for thread in threads if thread.state == state]
    if workspace_text:
        threads = [thread for thread in threads if not thread.workspace or thread.workspace == workspace_text]
    threads.sort(key=lambda thread: (thread.priority, thread.updated_at), reverse=True)
    return threads


def due_threads(workspace: str | Path | None = None) -> list[WorkThread]:
    now = _now()
    return [
        thread
        for thread in list_threads(workspace)
        if thread.due_at and thread.due_at <= now and thread.state in {"active", "waiting", "blocked"}
    ]


def review_due(workspace: str | Path, *, source: str = "autonomy") -> list[WorkThread]:
    reviewed: list[WorkThread] = []
    for thread in due_threads(workspace):
        reviewed.append(
            update_thread(
                thread.thread_id,
                last_note="reviewed due thread and kept next action in context",
                bump_due=True,
                source=source,
            )
        )
    return reviewed


def update_thread(
    thread_id: str,
    *,
    state: str | None = None,
    next_action: str | None = None,
    blockers: list[str] | None = None,
    artifacts: list[str] | None = None,
    last_note: str = "",
    bump_due: bool = False,
    source: str = "runtime",
) -> WorkThread:
    threads = list_threads(include_all=True)
    now = _now()
    out: list[WorkThread] = []
    updated: WorkThread | None = None
    for thread in threads:
        if thread.thread_id != thread_id:
            out.append(thread)
            continue
        data = asdict(thread)
        if state is not None:
            clean_state = str(state).strip().lower()
            if clean_state not in THREAD_STATUSES:
                raise ValueError(f"unknown thread state: {clean_state}")
            data["state"] = clean_state
        if next_action is not None:
            data["next_action"] = _clean(next_action, 400)
        if blockers is not None:
            data["blockers"] = _dedupe(blockers)
            if blockers and data["state"] == "active":
                data["state"] = "blocked"
        if artifacts is not None:
            data["artifacts"] = _dedupe([*thread.artifacts, *artifacts])
        if bump_due:
            data["due_at"] = _next_due(thread.cadence, now)
        if last_note:
            data["history"] = _trim_history([_history(source, last_note, now), *thread.history])
        data["updated_at"] = now
        updated = WorkThread(**data)
        out.append(updated)
    if updated is None:
        raise KeyError(f"work thread not found: {thread_id}")
    _write(out)
    return updated


def status(workspace: str | Path | None = None) -> ThreadStatus:
    active_threads = list_threads(workspace)
    now = _now()
    return ThreadStatus(
        path=threads_path(),
        active=sum(1 for thread in active_threads if thread.state == "active"),
        blocked=sum(1 for thread in active_threads if thread.state == "blocked"),
        waiting=sum(1 for thread in active_threads if thread.state == "waiting"),
        due=sum(1 for thread in active_threads if thread.due_at and thread.due_at <= now),
    )


def prompt_section(workspace: str | Path, *, limit: int = 6) -> str:
    threads = list_threads(workspace)[: max(1, limit)]
    if not threads:
        return ""
    lines = ["# Autonomous Work Threads"]
    for thread in threads:
        due = f" | due: {_format_time(thread.due_at)}" if thread.due_at else ""
        lines.append(f"- {thread.state} P{thread.priority} {thread.title}{due}")
        if thread.next_action:
            lines.append(f"  - next: {thread.next_action}")
        if thread.blockers:
            lines.append(f"  - blockers: {'; '.join(thread.blockers[:3])}")
    return "\n".join(lines)


def _replace_thread(updated: WorkThread, threads: list[WorkThread]) -> None:
    _write([updated if thread.thread_id == updated.thread_id else thread for thread in threads])


def _read() -> list[WorkThread]:
    path = threads_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("threads") if isinstance(data, dict) else []
    out: list[WorkThread] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                WorkThread(
                    thread_id=str(item.get("thread_id") or ""),
                    goal_id=str(item.get("goal_id") or ""),
                    title=str(item.get("title") or ""),
                    state=str(item.get("state") or "active"),
                    workspace=str(item.get("workspace") or ""),
                    priority=int(item.get("priority") or 3),
                    next_action=str(item.get("next_action") or ""),
                    blockers=[str(value) for value in item.get("blockers", [])],
                    due_at=int(item.get("due_at") or 0),
                    cadence=str(item.get("cadence") or ""),
                    tags=[str(value) for value in item.get("tags", [])],
                    artifacts=[str(value) for value in item.get("artifacts", [])],
                    history=[value for value in item.get("history", []) if isinstance(value, dict)],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [thread for thread in out if thread.thread_id and thread.goal_id and thread.title]


def _write(threads: list[WorkThread]) -> None:
    path = threads_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {"schema": SCHEMA_VERSION, "threads": [asdict(thread) for thread in threads]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)
    settings.restrict_file_permissions(path)


def _next_action(goal: goals.Goal, prompt_text: str) -> str:
    lower = " ".join([goal.title, goal.description, prompt_text, " ".join(goal.tags)]).lower()
    if any(term in lower for term in ("business", "income", "revenue", "sales", "customer")):
        return "Define offer, audience, launch asset, revenue tracker, and execute the safest local first step."
    if any(term in lower for term in ("monitor", "track", "watch", "keep an eye")):
        return "Check latest status, record a short result, update blockers, and schedule the next review."
    if any(term in lower for term in ("learn", "skill", "mcp", "repository", "repo", "reverse engineer")):
        return "Inspect the reference, extract the reusable workflow, save memory, and create a skill if it repeats."
    if any(term in lower for term in ("ui", "webui", "design", "frontend")):
        return "Open the UI, inspect the current screen, make the smallest visual upgrade, then verify in browser."
    return "Choose the next safe concrete step, execute what is local, and ask only for risky external approval."


def _blockers(text: str) -> list[str]:
    lower = text.lower()
    blockers: list[str] = []
    if any(term in lower for term in APPROVAL_TERMS):
        blockers.append("Needs approval before posting, messaging, spending, account changes, or credential use.")
    if any(term in lower for term in ("reverse engineer", "game", "server")):
        blockers.append("Needs legal and scope clarity before bypassing protections or inspecting private systems.")
    return blockers


def _due_at(goal: goals.Goal, now: int) -> int:
    return int(goal.next_review_at or _next_due(goal.cadence, now))


def _next_due(cadence: str, now: int) -> int:
    value = str(cadence or "").strip().lower()
    if value in {"daily", "day"}:
        return now + 24 * 60 * 60
    if value in {"weekly", "week"}:
        return now + 7 * 24 * 60 * 60
    if value in {"monthly", "month"}:
        return now + 30 * 24 * 60 * 60
    return 0


def _history(source: str, text: str, created_at: int) -> dict[str, Any]:
    return {
        "at": created_at,
        "source": _clean(source, 80),
        "text": _clean(text, 500),
    }


def _trim_history(items: list[dict[str, Any]], limit: int = 30) -> list[dict[str, Any]]:
    return items[:limit]


def _clean(value: str, limit: int = 500) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = _clean(str(item or ""), 220)
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _format_time(value: int) -> str:
    if not value:
        return "not scheduled"
    try:
        return time.strftime("%Y-%m-%d", time.localtime(value))
    except Exception:
        return "unknown"


def _now() -> int:
    return int(time.time())
