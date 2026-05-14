"""Persistent objectives for Crypt's autonomous assistant layer."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import redact, settings


SCHEMA_VERSION = 1
STATUSES = {"active", "paused", "completed", "cancelled"}


@dataclass(frozen=True)
class Goal:
    goal_id: str
    title: str
    description: str = ""
    status: str = "active"
    priority: int = 3
    workspace: str = ""
    success_metric: str = ""
    cadence: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0
    next_review_at: int = 0
    last_result: str = ""


def goals_path() -> Path:
    return settings.APP_DIR / "goals" / "goals.json"


def add_goal(
    title: str,
    *,
    description: str = "",
    workspace: str | Path | None = None,
    success_metric: str = "",
    cadence: str = "",
    priority: int = 3,
    tags: list[str] | None = None,
) -> Goal:
    clean_title = _clean(title)
    if not clean_title:
        raise ValueError("goal title cannot be empty")
    now = _now()
    goal = Goal(
        goal_id=f"goal_{uuid.uuid4().hex[:10]}",
        title=clean_title,
        description=_clean(description, 2_000),
        status="active",
        priority=max(1, min(5, int(priority or 3))),
        workspace=str(Path(workspace).expanduser().resolve()) if workspace else "",
        success_metric=_clean(success_metric, 1_000),
        cadence=_clean(cadence, 160),
        tags=_dedupe(tags or []),
        created_at=now,
        updated_at=now,
        next_review_at=_next_review(cadence, now),
    )
    goals = list_goals(include_all=True)
    goals.append(goal)
    _write(goals)
    return goal


def update_goal(goal_id: str, **values: Any) -> Goal:
    goals = list_goals(include_all=True)
    out: list[Goal] = []
    updated: Goal | None = None
    for goal in goals:
        if goal.goal_id != goal_id:
            out.append(goal)
            continue
        data = asdict(goal)
        for key in ("title", "description", "success_metric", "cadence", "last_result"):
            if key in values and values[key] is not None:
                data[key] = _clean(str(values[key]), 2_000)
        if "status" in values and values["status"] is not None:
            status = str(values["status"]).strip().lower()
            if status not in STATUSES:
                raise ValueError(f"unknown goal status: {status}")
            data["status"] = status
        if "priority" in values and values["priority"] is not None:
            data["priority"] = max(1, min(5, int(values["priority"])))
        if "tags" in values and values["tags"] is not None:
            data["tags"] = _dedupe([str(tag) for tag in values["tags"]])
        if "next_review_at" in values and values["next_review_at"] is not None:
            data["next_review_at"] = int(values["next_review_at"])
        elif "cadence" in values:
            data["next_review_at"] = _next_review(str(data.get("cadence") or ""), _now())
        data["updated_at"] = _now()
        updated = Goal(**data)
        out.append(updated)
    if updated is None:
        raise KeyError(f"goal not found: {goal_id}")
    _write(out)
    return updated


def list_goals(
    workspace: str | Path | None = None,
    *,
    status: str = "active",
    include_all: bool = False,
) -> list[Goal]:
    workspace_text = str(Path(workspace).expanduser().resolve()) if workspace else ""
    goals = _read()
    if not include_all:
        goals = [goal for goal in goals if goal.status == status]
    if workspace_text:
        goals = [goal for goal in goals if not goal.workspace or goal.workspace == workspace_text]
    goals.sort(key=lambda goal: (goal.priority, goal.updated_at), reverse=True)
    return goals


def due_goals(workspace: str | Path | None = None) -> list[Goal]:
    now = _now()
    return [
        goal
        for goal in list_goals(workspace)
        if goal.next_review_at and goal.next_review_at <= now
    ]


def prompt_section(workspace: str | Path, *, limit: int = 6) -> str:
    active = list_goals(workspace)[: max(1, limit)]
    if not active:
        return ""
    lines = ["# Active Goals"]
    for goal in active:
        line = f"- P{goal.priority} {goal.title}"
        if goal.success_metric:
            line += f" | success: {goal.success_metric}"
        if goal.cadence:
            line += f" | cadence: {goal.cadence}"
        lines.append(line)
        if goal.description:
            lines.append(f"  - {goal.description}")
    return "\n".join(lines)


def format_goals(workspace: str | Path | None = None, *, include_all: bool = False) -> str:
    goals = list_goals(workspace, include_all=include_all)
    if not goals:
        return "no goals found"
    lines = []
    for goal in goals:
        when = time.strftime("%Y-%m-%d", time.localtime(goal.updated_at or goal.created_at))
        tags = f" [{', '.join(goal.tags)}]" if goal.tags else ""
        lines.append(f"{goal.goal_id} P{goal.priority} {goal.status} {when}{tags} - {goal.title}")
        if goal.success_metric:
            lines.append(f"  success: {goal.success_metric}")
        if goal.last_result:
            lines.append(f"  last: {goal.last_result}")
    return "\n".join(lines)


def _read() -> list[Goal]:
    path = goals_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("goals") if isinstance(data, dict) else []
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                Goal(
                    goal_id=str(item.get("goal_id") or ""),
                    title=str(item.get("title") or ""),
                    description=str(item.get("description") or ""),
                    status=str(item.get("status") or "active"),
                    priority=int(item.get("priority") or 3),
                    workspace=str(item.get("workspace") or ""),
                    success_metric=str(item.get("success_metric") or ""),
                    cadence=str(item.get("cadence") or ""),
                    tags=[str(tag) for tag in item.get("tags", [])],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                    next_review_at=int(item.get("next_review_at") or 0),
                    last_result=str(item.get("last_result") or ""),
                )
            )
        except Exception:
            continue
    return [goal for goal in out if goal.goal_id and goal.title]


def _write(goals: list[Goal]) -> None:
    path = goals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {"schema": SCHEMA_VERSION, "goals": [asdict(goal) for goal in goals]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)
    settings.restrict_file_permissions(path)


def _next_review(cadence: str, now: int) -> int:
    value = str(cadence or "").strip().lower()
    if value in {"daily", "day"}:
        return now + 24 * 60 * 60
    if value in {"weekly", "week"}:
        return now + 7 * 24 * 60 * 60
    if value in {"monthly", "month"}:
        return now + 30 * 24 * 60 * 60
    return 0


def _clean(value: str, limit: int = 500) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        clean = _clean(item, 80)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _now() -> int:
    return int(time.time())
