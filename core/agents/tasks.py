from __future__ import annotations

import contextvars
import itertools
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .contracts import AgentDefinition, AgentTaskStatus


Runner = Callable[..., str]

_LOCK = threading.RLock()
_COUNTER = itertools.count(1)
_TASKS: dict[str, "AgentTask"] = {}
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="crypt-agent")


@dataclass
class AgentTask:
    id: str
    name: str
    agent_type: str
    prompt: str
    status: AgentTaskStatus = AgentTaskStatus.QUEUED
    context: str | None = None
    scope: str = ""
    write_paths: list[str] = field(default_factory=list)
    isolation: str = "shared"
    worktree_path: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    result: str = ""
    error: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    pending_messages: list[str] = field(default_factory=list)
    cancel_requested: bool = False
    future: Future | None = field(default=None, repr=False)


def start_agent_task(
    *,
    definition: AgentDefinition,
    name: str,
    prompt: str,
    context: str | None,
    scope: str = "",
    write_paths: list[str] | None = None,
    isolation: str = "shared",
    worktree_path: str = "",
    runner: Runner,
    background: bool,
) -> AgentTask:
    task = AgentTask(
        id=f"agent_{next(_COUNTER):04d}",
        name=name or definition.ui_label or definition.name,
        agent_type=definition.name,
        prompt=prompt,
        context=context,
        scope=scope,
        write_paths=list(write_paths or []),
        isolation=isolation,
        worktree_path=worktree_path,
    )
    with _LOCK:
        _TASKS[task.id] = task
    _record(task, "agent_task_created", f"{task.agent_type}: {task.name}")
    if background:
        context = contextvars.copy_context()
        task.future = _POOL.submit(context.run, _execute, task, definition, runner)
    else:
        _execute(task, definition, runner)
    return task


def continue_agent_task(task_id: str, message: str, *, runner: Runner, background: bool = True) -> AgentTask:
    previous = get(task_id)
    if previous is None:
        raise KeyError(f"unknown agent task: {task_id}")
    from .registry import get_agent

    definition = get_agent(previous.agent_type)
    context = (
        f"Previous task {previous.id} prompt:\n{previous.prompt}\n\n"
        f"Previous result:\n{previous.result or previous.error or '(no result yet)'}"
    )
    return start_agent_task(
        definition=definition,
        name=previous.name + " follow-up",
        prompt=message,
        context=context,
        scope=previous.scope,
        write_paths=previous.write_paths,
        isolation=previous.isolation,
        worktree_path=previous.worktree_path,
        runner=runner,
        background=background,
    )


def queue_message(task_id: str, message: str) -> str:
    task = require(task_id)
    with _LOCK:
        task.pending_messages.append(str(message))
    _record(task, "agent_task_message", str(message)[:200])
    return "message recorded; start a continuation task for the agent to act on it"


def request_stop(task_id: str, reason: str = "") -> str:
    task = require(task_id)
    with _LOCK:
        task.cancel_requested = True
        if task.status in {AgentTaskStatus.QUEUED} and task.future and task.future.cancel():
            task.status = AgentTaskStatus.CANCELLED
            task.finished_at = time.time()
            return "agent task cancelled before start"
        if task.status not in {AgentTaskStatus.COMPLETED, AgentTaskStatus.FAILED, AgentTaskStatus.CANCELLED}:
            task.status = AgentTaskStatus.CANCEL_REQUESTED
    _record(task, "agent_task_stop_requested", reason or "stop requested")
    return "stop requested; running provider calls may finish before cancellation takes effect"


def get(task_id: str) -> AgentTask | None:
    with _LOCK:
        return _TASKS.get(task_id)


def require(task_id: str) -> AgentTask:
    task = get(task_id)
    if task is None:
        raise KeyError(f"unknown agent task: {task_id}")
    _refresh_task(task)
    return task


def list_tasks(status: str | None = None) -> list[AgentTask]:
    with _LOCK:
        tasks = list(_TASKS.values())
    for task in tasks:
        _refresh_task(task)
    if status:
        tasks = [task for task in tasks if task.status.value == status]
    return sorted(tasks, key=lambda item: item.started_at)


def format_task(task: AgentTask, *, tail: int | None = None) -> str:
    _refresh_task(task)
    lines = [
        f"{task.id} {task.status.value} {task.agent_type} - {task.name}",
        f"scope: {task.scope or '(none)'}",
    ]
    if task.write_paths:
        lines.append("write_paths: " + ", ".join(task.write_paths))
    if task.worktree_path:
        lines.append(f"worktree: {task.worktree_path}")
    if task.pending_messages:
        lines.append(f"pending_messages: {len(task.pending_messages)}")
    body = task.result or task.error
    if body:
        body_lines = body.splitlines()
        if tail:
            body_lines = body_lines[-max(1, tail):]
        lines.append("output:")
        lines.extend(body_lines)
    return "\n".join(lines)


def worktree_diff(task_id: str, *, max_chars: int = 12000) -> str:
    task = require(task_id)
    if not task.worktree_path:
        return "agent task has no isolated worktree"
    from core import worktrees

    files = worktrees.changed_files(task.worktree_path)
    untracked = worktrees.untracked_files(task.worktree_path)
    patch = worktrees.diff(task.worktree_path).strip()
    lines = [f"worktree: {task.worktree_path}"]
    if files:
        lines.append("changed_files:")
        lines.extend(f"- {path}" for path in files)
    else:
        lines.append("changed_files: none")
    if patch:
        if max_chars > 0 and len(patch) > max_chars:
            patch = patch[:max_chars] + "\n... [diff truncated]"
        lines.extend(["diff:", patch])
    else:
        lines.append("diff: none")
    if untracked:
        lines.append("untracked_file_previews:")
        remaining = max_chars
        for rel in untracked[:10]:
            preview = _untracked_preview(Path(task.worktree_path) / rel, remaining)
            remaining = max(0, remaining - len(preview))
            lines.extend([f"--- {rel}", preview])
    return "\n".join(lines)


def cleanup_worktree(task_id: str, *, force: bool = False) -> str:
    task = require(task_id)
    if not task.worktree_path:
        return "agent task has no isolated worktree"
    if task.status not in {
        AgentTaskStatus.COMPLETED,
        AgentTaskStatus.FAILED,
        AgentTaskStatus.CANCELLED,
    }:
        return f"agent task is {task.status.value}; wait for it to finish before cleanup"
    from core import runtime, worktrees

    main_cwd = runtime.cwd() or task.worktree_path
    return worktrees.remove(main_cwd, task.worktree_path, force=force)


def forget(task_id: str) -> str:
    task = require(task_id)
    if task.status not in {
        AgentTaskStatus.COMPLETED,
        AgentTaskStatus.FAILED,
        AgentTaskStatus.CANCELLED,
    }:
        return f"agent task is {task.status.value}; wait for it to finish before forgetting"
    with _LOCK:
        _TASKS.pop(task_id, None)
    return f"forgot agent task: {task_id}"


def reset() -> None:
    with _LOCK:
        _TASKS.clear()


def _execute(task: AgentTask, definition: AgentDefinition, runner: Runner) -> None:
    with _LOCK:
        task.status = AgentTaskStatus.RUNNING
        task.started_at = time.time()
    _record(task, "agent_task_started", f"{task.agent_type}: {task.name}")
    try:
        if task.cancel_requested:
            task.status = AgentTaskStatus.CANCELLED
            task.finished_at = time.time()
            return
        result = runner(
            task.prompt,
            context=task.context,
            agent_type=definition.name,
            write_paths=task.write_paths,
            task_id=task.id,
            worktree_path=task.worktree_path or None,
        )
        with _LOCK:
            task.result = result or "(no output)"
            task.status = AgentTaskStatus.CANCELLED if task.cancel_requested else AgentTaskStatus.COMPLETED
            task.finished_at = time.time()
        source = "agent_task_cancelled" if task.status == AgentTaskStatus.CANCELLED else "agent_task_completed"
        _record(task, source, task.result[:300])
    except Exception as exc:
        with _LOCK:
            task.error = f"{type(exc).__name__}: {exc}"
            task.status = AgentTaskStatus.FAILED
            task.finished_at = time.time()
        _record(task, "agent_task_failed", task.error)


def _refresh_task(task: AgentTask) -> None:
    future = task.future
    if future is None or not future.done():
        return
    try:
        future.result()
    except Exception:
        pass


def _record(task: AgentTask, source: str, summary: str) -> None:
    try:
        from core import evidence, tracing

        entry = evidence.record("agent", source, summary, task_id=task.id)
        task.evidence_ids.append(entry.id)
        tracing.emit(
            source,
            task_id=task.id,
            agent_type=task.agent_type,
            status=task.status.value,
            summary=summary,
        )
    except Exception:
        return


def _untracked_preview(path: Path, remaining: int) -> str:
    if remaining <= 0:
        return "... [preview omitted]"
    try:
        if path.stat().st_size > 64_000:
            return "... [untracked file too large to preview]"
        data = path.read_bytes()
    except OSError as exc:
        return f"... [untracked file unreadable: {exc}]"
    if b"\x00" in data[:4096]:
        return "... [binary untracked file]"
    text = data.decode("utf-8", errors="replace")
    if len(text) > remaining:
        return text[:remaining] + "\n... [preview truncated]"
    return text
