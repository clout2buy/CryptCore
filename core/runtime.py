"""Runtime hooks shared between core and optional tools.

Holds session-scoped state that tools and the loop both need to read or write
without forming an import cycle. Configured once per session by core.loop.run().
"""
from __future__ import annotations

import os
import contextvars
from contextlib import contextmanager
from pathlib import Path
from typing import Callable


_provider = None
_cwd = "."
_subagent_runner: Callable[..., str] | None = None
_session = None
_approval_mode = os.getenv("CRYPT_APPROVAL", "edits").strip().lower()
_thinking_mode = os.getenv("CRYPT_THINKING_MODE", "fast").strip().lower()
_render_tools = contextvars.ContextVar("crypt_render_tools", default=True)
_cwd_context = contextvars.ContextVar("crypt_cwd", default=None)
_subagent_tools = contextvars.ContextVar("crypt_subagent_tools", default=None)
_approval_callback = contextvars.ContextVar("crypt_approval_callback", default=None)
_write_scope = contextvars.ContextVar("crypt_write_scope", default=None)
_agent_type = contextvars.ContextVar("crypt_agent_type", default=None)
_agent_task_id = contextvars.ContextVar("crypt_agent_task_id", default=None)
_git_snapshot_cache: dict[str, str] = {}

APPROVAL_NORMAL = "normal"
APPROVAL_EDITS = "edits"
APPROVAL_ALL = "all"
APPROVAL_MODES = (APPROVAL_NORMAL, APPROVAL_EDITS, APPROVAL_ALL)
if _approval_mode not in APPROVAL_MODES:
    _approval_mode = APPROVAL_EDITS
THINKING_FAST = "fast"
THINKING_THINK = "think"
THINKING_ULTRA = "ultra"
THINKING_MODES = (THINKING_FAST, THINKING_THINK, THINKING_ULTRA)
if _thinking_mode not in THINKING_MODES:
    _thinking_mode = THINKING_FAST
AUTO_EDIT_TOOLS = {
    "edit_file",
    "multi_edit",
    "write_file",
}
AUTO_WORK_TOOLS = AUTO_EDIT_TOOLS | {
    "bash",
    "bash_start",
    "open_file",
    "web_fetch",
    "web_search",
}


def configure(
    provider,
    cwd: str,
    subagent_runner: Callable[..., str] | None = None,
    session=None,
) -> None:
    global _provider, _cwd, _subagent_runner, _session
    _provider = provider
    _cwd = cwd
    _subagent_runner = subagent_runner
    _session = session
    os.environ["CRYPT_ROOT"] = str(cwd)


def provider():
    return _provider


def session():
    return _session


def set_session(session_obj) -> None:
    global _session
    _session = session_obj


def session_id() -> str | None:
    return getattr(_session, "id", None)


def cwd() -> str:
    return _cwd_context.get() or _cwd


def context_cwd() -> str | None:
    return _cwd_context.get()


def set_cwd(path: str) -> Path:
    """Move the workspace mid-session. Updates CRYPT_ROOT so file tools and bash agree."""
    global _cwd
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"workspace does not exist: {p}")
    if not p.is_dir():
        raise NotADirectoryError(f"workspace is not a directory: {p}")
    _cwd = str(p)
    os.environ["CRYPT_ROOT"] = str(p)
    invalidate_git_snapshot()
    return p


def git_snapshot(cwd: str) -> str:
    """Cached startup git snapshot. Each cwd gets computed once per session
    so the system prompt stays cache-friendly and turns don't pay a 50-200ms
    git tax. Call invalidate_git_snapshot() if you need a refresh."""
    if cwd in _git_snapshot_cache:
        return _git_snapshot_cache[cwd]
    from . import prompt as _prompt  # avoid import cycle at module load

    snapshot = _prompt.compute_git_snapshot(cwd)
    _git_snapshot_cache[cwd] = snapshot
    return snapshot


def invalidate_git_snapshot() -> None:
    _git_snapshot_cache.clear()


def yolo() -> bool:
    return _approval_mode == APPROVAL_ALL


def set_yolo(on: bool) -> bool:
    set_approval_mode(APPROVAL_ALL if on else APPROVAL_NORMAL)
    return yolo()


def approval_mode() -> str:
    return _approval_mode


def approval_label() -> str:
    if _approval_mode == APPROVAL_EDITS:
        return "auto-work"
    if _approval_mode == APPROVAL_ALL:
        return "yolo-all"
    return "manual"


def set_approval_mode(mode: str) -> str:
    global _approval_mode
    if mode not in APPROVAL_MODES:
        raise ValueError(f"unknown approval mode: {mode}")
    _approval_mode = mode
    return _approval_mode


def can_auto_approve(tool_name: str) -> bool:
    if _approval_mode == APPROVAL_ALL:
        return True
    if _approval_mode == APPROVAL_EDITS:
        return tool_name in AUTO_WORK_TOOLS
    return False


def can_auto_approve_plan() -> bool:
    return _approval_mode == APPROVAL_ALL


def approval_callback():
    return _approval_callback.get()


@contextmanager
def approval_handler(callback):
    token = _approval_callback.set(callback)
    try:
        yield
    finally:
        _approval_callback.reset(token)


def show_thinking() -> bool:
    return _thinking_mode != THINKING_FAST


def set_show_thinking(on: bool) -> bool:
    set_thinking_mode(THINKING_THINK if on else THINKING_FAST)
    return show_thinking()


def thinking_mode() -> str:
    return _thinking_mode


def set_thinking_mode(mode: str) -> str:
    global _thinking_mode
    normalized = (mode or THINKING_FAST).strip().lower()
    aliases = {
        "off": THINKING_FAST,
        "none": THINKING_FAST,
        "on": THINKING_THINK,
        "thinking": THINKING_THINK,
        "high": THINKING_ULTRA,
        "xhigh": THINKING_ULTRA,
        "extra": THINKING_ULTRA,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in THINKING_MODES:
        raise ValueError(f"unknown thinking mode: {mode}")
    _thinking_mode = normalized
    return _thinking_mode


def reasoning_effort() -> str | None:
    if _thinking_mode == THINKING_THINK:
        return "medium"
    if _thinking_mode == THINKING_ULTRA:
        return "high"
    return None


def thinking_budget() -> int:
    if _thinking_mode == THINKING_THINK:
        return 4_096
    if _thinking_mode == THINKING_ULTRA:
        return 16_384
    return 0


def render_tools() -> bool:
    return bool(_render_tools.get())


@contextmanager
def tool_render(enabled: bool):
    token = _render_tools.set(bool(enabled))
    try:
        yield
    finally:
        _render_tools.reset(token)


@contextmanager
def cwd_context(path: str | Path | None):
    if path is None:
        yield
        return
    p = str(Path(path).expanduser().resolve())
    token = _cwd_context.set(p)
    try:
        yield
    finally:
        _cwd_context.reset(token)


def run_subagent(
    prompt: str,
    context: str | None = None,
    *,
    agent_type: str = "explorer",
    write_paths: list[str] | None = None,
    task_id: str | None = None,
    worktree_path: str | None = None,
) -> str:
    if _subagent_runner is None:
        return "spawn_agent unavailable: no active subagent runner"
    return _subagent_runner(
        prompt,
        context,
        agent_type=agent_type,
        write_paths=write_paths or [],
        task_id=task_id,
        worktree_path=worktree_path,
    )


@contextmanager
def subagent_context(
    *,
    agent_type: str,
    allowed_tools: set[str] | frozenset[str],
    write_paths: list[str] | tuple[str, ...] | None = None,
    task_id: str | None = None,
):
    tool_token = _subagent_tools.set(frozenset(allowed_tools))
    scope_token = _write_scope.set(tuple(write_paths or ()))
    type_token = _agent_type.set(agent_type)
    task_token = _agent_task_id.set(task_id)
    try:
        yield
    finally:
        _agent_task_id.reset(task_token)
        _agent_type.reset(type_token)
        _write_scope.reset(scope_token)
        _subagent_tools.reset(tool_token)


def current_subagent_tools() -> frozenset[str] | None:
    return _subagent_tools.get()


def current_write_scope() -> tuple[str, ...] | None:
    return _write_scope.get()


def current_agent_type() -> str | None:
    return _agent_type.get()


def current_agent_task_id() -> str | None:
    return _agent_task_id.get()


def current_subagent_can_use_tool(tool_name: str) -> bool:
    allowed = current_subagent_tools()
    return bool(allowed and tool_name in allowed)


def background_job_summaries() -> list[str]:
    try:
        from . import background

        out: list[str] = []
        for job in background.list_jobs():
            out.append(f"{job.id}: {background.status(job)} - {job.command}")
        return out
    except Exception:
        return []


def agent_task_summaries() -> list[str]:
    try:
        from .agents import tasks

        out: list[str] = []
        for task in tasks.list_tasks():
            if task.status.value in {"queued", "running", "cancel_requested"}:
                out.append(f"{task.id}: {task.status.value} {task.agent_type} - {task.name}")
        return out
    except Exception:
        return []
