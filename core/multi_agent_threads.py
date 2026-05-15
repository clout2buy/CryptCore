"""Durable coordination for multi-agent work threads."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import agent_profiles, session, settings


SCHEMA_VERSION = 1
ITEM_STATES = {"queued", "running", "blocked", "review", "done", "cancelled"}
THREAD_STATES = {"active", "blocked", "review", "merged", "cancelled"}


@dataclass(frozen=True)
class AgentAssignment:
    item_id: str
    agent_id: str
    agent_name: str
    responsibility: str
    write_scope: list[str] = field(default_factory=list)
    state: str = "queued"
    artifacts: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    review: str = ""
    result: str = ""
    updated_at: int = 0


@dataclass(frozen=True)
class MultiAgentThread:
    thread_id: str
    title: str
    mission_id: str = ""
    state: str = "active"
    assignments: list[AgentAssignment] = field(default_factory=list)
    merge_summary: str = ""
    created_at: int = 0
    updated_at: int = 0


def state_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "multi_agent" / "threads.json"


def create_thread(
    cwd: str | Path,
    title: str,
    assignments: list[dict[str, Any]],
    *,
    mission_id: str = "",
) -> MultiAgentThread:
    clean_title = _clean(title, 160)
    if not clean_title:
        raise ValueError("thread title is required")
    items = [_assignment_from_input(cwd, item) for item in assignments]
    if len(items) < 2:
        raise ValueError("multi-agent thread requires at least two assignments")
    _ensure_disjoint_scopes(items)
    now = _now()
    thread = MultiAgentThread(
        thread_id=_thread_id(clean_title),
        title=clean_title,
        mission_id=_clean(mission_id, 120),
        assignments=items,
        created_at=now,
        updated_at=now,
    )
    threads = [item for item in list_threads(cwd, include_all=True) if item.thread_id != thread.thread_id]
    threads.insert(0, thread)
    _write(cwd, threads)
    return thread


def update_assignment(
    cwd: str | Path,
    thread_id: str,
    item_id: str,
    *,
    state: str | None = None,
    artifacts: list[str] | None = None,
    blockers: list[str] | None = None,
    review: str | None = None,
    result: str | None = None,
) -> MultiAgentThread:
    threads = list_threads(cwd, include_all=True)
    out: list[MultiAgentThread] = []
    updated: MultiAgentThread | None = None
    now = _now()
    for thread in threads:
        if thread.thread_id != thread_id:
            out.append(thread)
            continue
        assignments: list[AgentAssignment] = []
        found = False
        for item in thread.assignments:
            if item.item_id != item_id:
                assignments.append(item)
                continue
            found = True
            data = asdict(item)
            if state is not None:
                data["state"] = _item_state(state)
            if artifacts is not None:
                data["artifacts"] = _dedupe([*item.artifacts, *artifacts])
            if blockers is not None:
                data["blockers"] = _dedupe(blockers)
                if blockers:
                    data["state"] = "blocked"
            if review is not None:
                data["review"] = _clean(review, 800)
            if result is not None:
                data["result"] = _clean(result, 1200)
            data["updated_at"] = now
            assignments.append(AgentAssignment(**data))
        if not found:
            raise KeyError(f"assignment not found: {item_id}")
        updated = _refresh_thread(thread, assignments, now=now)
        out.append(updated)
    if updated is None:
        raise KeyError(f"multi-agent thread not found: {thread_id}")
    _write(cwd, out)
    return updated


def complete_assignment(
    cwd: str | Path,
    thread_id: str,
    item_id: str,
    *,
    result: str,
    artifacts: list[str] | None = None,
    review: str = "",
) -> MultiAgentThread:
    return update_assignment(cwd, thread_id, item_id, state="done", result=result, artifacts=artifacts or [], review=review)


def list_threads(cwd: str | Path, *, include_all: bool = False, limit: int = 100) -> list[MultiAgentThread]:
    threads = _read(cwd)
    if not include_all:
        threads = [thread for thread in threads if thread.state not in {"merged", "cancelled"}]
    threads.sort(key=lambda item: item.updated_at, reverse=True)
    return threads[: max(1, limit)]


def snapshot(cwd: str | Path, *, limit: int = 8) -> dict[str, Any]:
    threads = list_threads(cwd, include_all=True, limit=limit)
    return {
        "path": str(state_path(cwd)),
        "count": len(threads),
        "threads": [asdict(thread) for thread in threads],
    }


def prompt_section(cwd: str | Path, *, limit: int = 4) -> str:
    threads = list_threads(cwd, limit=limit)
    if not threads:
        return ""
    lines = ["# Multi-Agent Work Threads"]
    for thread in threads:
        lines.append(f"- {thread.state}: {thread.title} ({len(thread.assignments)} assignment(s))")
        for item in thread.assignments[:3]:
            scope = f" scope={', '.join(item.write_scope[:3])}" if item.write_scope else ""
            lines.append(f"  - {item.state} {item.agent_name}: {item.responsibility}{scope}")
        if thread.merge_summary:
            lines.append(f"  - merge: {thread.merge_summary}")
    return "\n".join(lines)


def _assignment_from_input(cwd: str | Path, item: dict[str, Any]) -> AgentAssignment:
    agent_id = str(item.get("agent_id") or item.get("agentId") or "")
    profile = agent_profiles.get_profile(cwd, agent_id) if agent_id else None
    agent_name = _clean(item.get("agent_name") or item.get("agentName") or (profile.name if profile else ""), 80)
    responsibility = _clean(item.get("responsibility") or item.get("task") or "", 300)
    if not responsibility:
        raise ValueError("assignment responsibility is required")
    if not agent_name:
        agent_name = "Crypt Agent"
    write_scope = _dedupe([str(value) for value in item.get("write_scope", item.get("writeScope", [])) if str(value).strip()])
    seed = f"{agent_id}:{agent_name}:{responsibility}:{','.join(write_scope)}"
    return AgentAssignment(
        item_id="assign_" + hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:12],
        agent_id=agent_id,
        agent_name=agent_name,
        responsibility=responsibility,
        write_scope=write_scope,
        state=_item_state(str(item.get("state") or "queued")),
        updated_at=_now(),
    )


def _ensure_disjoint_scopes(items: list[AgentAssignment]) -> None:
    owners: dict[str, str] = {}
    for item in items:
        for scope in item.write_scope:
            key = scope.replace("\\", "/").strip().lower()
            if not key:
                continue
            if key in owners and owners[key] != item.item_id:
                raise ValueError(f"write scope conflict: {scope}")
            owners[key] = item.item_id


def _refresh_thread(thread: MultiAgentThread, assignments: list[AgentAssignment], *, now: int) -> MultiAgentThread:
    if any(item.state == "blocked" or item.blockers for item in assignments):
        state = "blocked"
    elif all(item.state in {"done", "cancelled"} for item in assignments):
        state = "merged"
    elif any(item.state == "review" for item in assignments):
        state = "review"
    else:
        state = "active"
    merge_summary = thread.merge_summary
    if state == "merged":
        merge_summary = _merge_summary(assignments)
    return MultiAgentThread(
        thread_id=thread.thread_id,
        title=thread.title,
        mission_id=thread.mission_id,
        state=state,
        assignments=assignments,
        merge_summary=merge_summary,
        created_at=thread.created_at,
        updated_at=now,
    )


def _merge_summary(assignments: list[AgentAssignment]) -> str:
    results = [f"{item.agent_name}: {item.result or item.responsibility}" for item in assignments if item.state == "done"]
    artifacts = _dedupe([artifact for item in assignments for artifact in item.artifacts])
    suffix = f" Artifacts: {', '.join(artifacts[:6])}." if artifacts else ""
    return _clean("Completed assignments. " + "; ".join(results[:6]) + "." + suffix, 1200)


def _read(cwd: str | Path) -> list[MultiAgentThread]:
    path = state_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[MultiAgentThread] = []
    for item in data.get("threads", []):
        if not isinstance(item, dict):
            continue
        try:
            assignments = [
                AgentAssignment(
                    item_id=str(raw.get("item_id") or ""),
                    agent_id=str(raw.get("agent_id") or ""),
                    agent_name=str(raw.get("agent_name") or "Crypt Agent"),
                    responsibility=str(raw.get("responsibility") or ""),
                    write_scope=[str(value) for value in raw.get("write_scope", [])],
                    state=_item_state(str(raw.get("state") or "queued")),
                    artifacts=[str(value) for value in raw.get("artifacts", [])],
                    blockers=[str(value) for value in raw.get("blockers", [])],
                    review=str(raw.get("review") or ""),
                    result=str(raw.get("result") or ""),
                    updated_at=int(raw.get("updated_at") or 0),
                )
                for raw in item.get("assignments", [])
                if isinstance(raw, dict)
            ]
            out.append(
                MultiAgentThread(
                    thread_id=str(item.get("thread_id") or ""),
                    title=str(item.get("title") or ""),
                    mission_id=str(item.get("mission_id") or ""),
                    state=str(item.get("state") or "active"),
                    assignments=assignments,
                    merge_summary=str(item.get("merge_summary") or ""),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [thread for thread in out if thread.thread_id and thread.title]


def _write(cwd: str | Path, threads: list[MultiAgentThread]) -> None:
    path = state_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "threads": [asdict(thread) for thread in threads[:100]]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _item_state(value: str) -> str:
    clean = str(value or "").strip().lower()
    return clean if clean in ITEM_STATES else "queued"


def _thread_id(title: str) -> str:
    return "multi_" + hashlib.sha1(f"{title}:{time.time()}".encode("utf-8", errors="replace")).hexdigest()[:12]


def _clean(value: object, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = _clean(item, 200)
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _now() -> int:
    return int(time.time())
