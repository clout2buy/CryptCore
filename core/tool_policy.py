"""Runtime tool policy checks.

Existing tools already enforce important invariants such as read-before-edit.
This module adds cross-tool policy: repeated write-loop detection, worker write
ownership, and evidence for allow/warn/block decisions.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from . import runtime


ALLOW = "allow"
WARN = "warn"
BLOCK = "block"


@dataclass(frozen=True)
class ToolPolicyDecision:
    action: str
    reason: str = ""
    required_action: str = ""

    @property
    def allowed(self) -> bool:
        return self.action != BLOCK


_LOCK = threading.RLock()
_WRITE_EVENTS: deque[tuple[float, str, str, str | None]] = deque(maxlen=80)
_WRITE_COUNTS: dict[str, int] = defaultdict(int)
_MUTATING_TOOLS = {"write_file", "edit_file", "multi_edit"}


def clear() -> None:
    with _LOCK:
        _WRITE_EVENTS.clear()
        _WRITE_COUNTS.clear()


def preflight(tool_name: str, args: dict) -> ToolPolicyDecision:
    if tool_name not in _MUTATING_TOOLS:
        return ToolPolicyDecision(ALLOW)
    paths = _mutating_paths(tool_name, args)
    scope_decision = _check_write_scope(paths)
    if scope_decision.action == BLOCK:
        return scope_decision
    loop_decision = _check_repeated_writes(tool_name, args, paths)
    if loop_decision.action != ALLOW:
        return loop_decision
    return ToolPolicyDecision(ALLOW)


def after_tool(tool_name: str, args: dict, *, ok: bool) -> None:
    if not ok:
        return
    if tool_name in {"read_file", "open_file"}:
        with _LOCK:
            for path in _read_paths(tool_name, args):
                _clear_write_events_for_path(path)
        return
    if tool_name not in _MUTATING_TOOLS:
        return
    signature = _write_signature(tool_name, args)
    task_id = runtime.current_agent_task_id()
    with _LOCK:
        for path in _mutating_paths(tool_name, args):
            key = _path_key(path)
            _WRITE_COUNTS[key] += 1
            _WRITE_EVENTS.append((time.time(), key, signature, task_id))


def record_decision(tool_name: str, decision: ToolPolicyDecision, *, task_id: str | None = None) -> None:
    if decision.action == ALLOW:
        return
    try:
        from . import evidence

        evidence.record(
            "policy",
            tool_name,
            f"{decision.action}: {decision.reason}",
            details={
                "action": decision.action,
                "reason": decision.reason,
                "required_action": decision.required_action,
            },
            task_id=task_id or runtime.current_agent_task_id(),
        )
    except Exception:
        return


def _check_write_scope(paths: list[Path]) -> ToolPolicyDecision:
    scope = runtime.current_write_scope()
    if not scope:
        return ToolPolicyDecision(ALLOW)
    allowed = [_resolve_scope(item) for item in scope]
    for path in paths:
        resolved = path.resolve()
        if any(_is_relative_to(resolved, item) for item in allowed):
            continue
        return ToolPolicyDecision(
            BLOCK,
            f"worker write outside assigned scope: {path}",
            "use a worker write_paths scope that includes this file, or edit locally",
        )
    return ToolPolicyDecision(ALLOW)


def _check_repeated_writes(tool_name: str, args: dict, paths: list[Path]) -> ToolPolicyDecision:
    if not paths:
        return ToolPolicyDecision(ALLOW)
    signature = _write_signature(tool_name, args)
    now = time.time()
    task_id = runtime.current_agent_task_id()
    with _LOCK:
        recent = [
            event
            for event in _WRITE_EVENTS
            if now - event[0] <= 300 and (task_id is None or event[3] == task_id)
        ]
        for path in paths:
            key = _path_key(path)
            same_path = [event for event in recent if event[1] == key]
            same_write = [event for event in same_path if event[2] == signature]
            if len(same_write) >= 2:
                return ToolPolicyDecision(
                    BLOCK,
                    f"identical write loop suspected for {path}",
                    "inspect or verify the artifact before rewriting it again",
                )
            if len(same_path) >= 3:
                return ToolPolicyDecision(
                    BLOCK,
                    f"write loop suspected for {path}",
                    "read, open, or verify the artifact before another rewrite",
                )
            if len(same_write) >= 1:
                return ToolPolicyDecision(
                    WARN,
                    f"same write signature already applied to {path}",
                    "inspect or verify the artifact before rewriting it again",
                )
    return ToolPolicyDecision(ALLOW)


def _mutating_paths(tool_name: str, args: dict) -> list[Path]:
    if not isinstance(args, dict):
        return []
    if tool_name in {"write_file", "edit_file"} and args.get("path"):
        return [_workspace_path(str(args["path"]))]
    if tool_name == "multi_edit":
        out: list[Path] = []
        raw = args.get("changes")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("path"):
                    out.append(_workspace_path(str(item["path"])))
        return out
    return []


def _read_paths(tool_name: str, args: dict) -> list[Path]:
    if not isinstance(args, dict):
        return []
    if tool_name in {"read_file", "open_file"} and args.get("path"):
        return [_workspace_path(str(args["path"]))]
    return []


def _clear_write_events_for_path(path: Path) -> None:
    key = _path_key(path)
    kept = [event for event in _WRITE_EVENTS if event[1] != key]
    _WRITE_EVENTS.clear()
    _WRITE_EVENTS.extend(kept)
    _WRITE_COUNTS.pop(key, None)


def _workspace_path(path: str) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    return Path(runtime.cwd()).resolve() / p


def _resolve_scope(path: str) -> Path:
    return _workspace_path(path).resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return path == parent


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).lower()
    except OSError:
        return str(path).lower()


def _write_signature(tool_name: str, args: dict) -> str:
    h = hashlib.sha256()
    h.update(tool_name.encode("utf-8", errors="ignore"))
    if isinstance(args, dict):
        for key in ("path", "content", "old", "new", "overwrite"):
            if key in args:
                h.update(str(args[key]).encode("utf-8", errors="ignore"))
        if isinstance(args.get("edits"), list):
            h.update(str(len(args["edits"])).encode())
        if isinstance(args.get("changes"), list):
            h.update(str(len(args["changes"])).encode())
    return h.hexdigest()
