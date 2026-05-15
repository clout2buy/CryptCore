"""Deterministic planner for autonomous mission work threads."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import work_threads


@dataclass(frozen=True)
class MissionStep:
    thread_id: str
    goal_id: str
    title: str
    action: str
    reason: str
    kind: str
    state: str
    priority: int
    due_at: int = 0
    blockers: list[str] = field(default_factory=list)
    task_title: str = ""
    needs_approval: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def plan_thread(thread: work_threads.WorkThread, *, now: int | None = None) -> MissionStep:
    current = int(time.time()) if now is None else int(now)
    blockers = list(thread.blockers or [])
    if blockers:
        blocker = blockers[0]
        needs_approval = "approval" in blocker.lower()
        return MissionStep(
            thread_id=thread.thread_id,
            goal_id=thread.goal_id,
            title=thread.title,
            action=f"Resolve blocker: {blocker}",
            reason="thread has a blocker before safe execution can continue",
            kind="approval_gate" if needs_approval else "unblock",
            state=thread.state,
            priority=thread.priority,
            due_at=thread.due_at,
            blockers=blockers,
            needs_approval=needs_approval,
        )

    if thread.due_at and thread.due_at <= current:
        return MissionStep(
            thread_id=thread.thread_id,
            goal_id=thread.goal_id,
            title=thread.title,
            action="Review the latest state, record what changed, and choose the next concrete step.",
            reason="thread review is due",
            kind="review",
            state=thread.state,
            priority=thread.priority,
            due_at=thread.due_at,
        )

    task = _first_pending_task(thread)
    if task:
        title = str(task.get("title") or "Complete the next pending task").strip()
        return MissionStep(
            thread_id=thread.thread_id,
            goal_id=thread.goal_id,
            title=thread.title,
            action=title,
            reason="first pending task in the mission checklist",
            kind="task",
            state=thread.state,
            priority=thread.priority,
            due_at=thread.due_at,
            task_title=title,
        )

    if thread.next_action:
        return MissionStep(
            thread_id=thread.thread_id,
            goal_id=thread.goal_id,
            title=thread.title,
            action=thread.next_action,
            reason="thread already has an explicit next action",
            kind="next_action",
            state=thread.state,
            priority=thread.priority,
            due_at=thread.due_at,
        )

    return MissionStep(
        thread_id=thread.thread_id,
        goal_id=thread.goal_id,
        title=thread.title,
        action="Define the next safe concrete step and record success evidence.",
        reason="thread has no current operating step",
        kind="maintain",
        state=thread.state,
        priority=thread.priority,
        due_at=thread.due_at,
    )


def plan_workspace(
    workspace: str | Path | None = None,
    *,
    limit: int = 8,
    now: int | None = None,
) -> list[MissionStep]:
    threads = work_threads.list_threads(workspace)[: max(1, limit)]
    return [plan_thread(thread, now=now) for thread in threads]


def review_workspace(
    workspace: str | Path | None = None,
    *,
    limit: int = 8,
    source: str = "mission-brain",
) -> list[MissionStep]:
    threads = {thread.thread_id: thread for thread in work_threads.list_threads(workspace)[: max(1, limit)]}
    steps = [plan_thread(thread) for thread in threads.values()]
    for step in steps:
        thread = threads.get(step.thread_id)
        if not thread or not step.action or thread.next_action == step.action:
            continue
        work_threads.update_thread(
            step.thread_id,
            next_action=step.action,
            last_note=f"selected {step.kind} step: {step.reason}",
            source=source,
        )
    return steps


def prompt_section(workspace: str | Path, *, limit: int = 4) -> str:
    steps = plan_workspace(workspace, limit=limit)
    if not steps:
        return ""
    lines = ["# Mission Brain"]
    for step in steps:
        due = f" | due: {_format_time(step.due_at)}" if step.due_at else ""
        gate = " | needs approval" if step.needs_approval else ""
        lines.append(f"- {step.kind} P{step.priority} {step.title}{due}{gate}")
        lines.append(f"  - next: {step.action}")
    return "\n".join(lines)


def _first_pending_task(thread: work_threads.WorkThread) -> dict | None:
    for task in thread.tasks:
        if str(task.get("status") or "pending").lower() != "done":
            return task
    return None


def _format_time(value: int) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(value))
    except Exception:
        return "unknown"
