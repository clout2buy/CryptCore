"""Compact mobile companion state for the WebUI."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def snapshot(cwd: str | Path, data: dict[str, Any]) -> dict[str, Any]:
    personal = data.get("personalOS") or {}
    summary = personal.get("summary") or {}
    memory = data.get("memoryJournal") or {}
    artifacts = data.get("artifactSummary") or {}
    approvals = data.get("externalDrafts") or {}
    notifications = data.get("notifications") or {}
    status = str(personal.get("status") or "ready")
    active_threads = int(summary.get("activeThreads") or 0)
    approval_count = int(approvals.get("pending") or summary.get("approvals") or 0)
    unread = int(notifications.get("unread") or 0)
    return {
        "workspace": str(Path(cwd).expanduser().resolve()),
        "status": status,
        "statusText": _status_text(status, active_threads, approval_count, unread),
        "tabs": [
            {"view": "chat", "label": "Chat", "badge": ""},
            {"view": "missions", "label": "Missions", "badge": _badge(active_threads)},
            {"view": "memory", "label": "Memory", "badge": _badge(int(memory.get("openLoopCount") or 0))},
            {"view": "files", "label": "Files", "badge": _badge(int(artifacts.get("total") or 0))},
        ],
        "coreBadge": _badge(max(approval_count, unread)),
        "primaryAction": "Say it normally. Crypt routes the rest.",
    }


def _status_text(status: str, active_threads: int, approvals: int, unread: int) -> str:
    if approvals:
        return f"{approvals} approval(s) waiting"
    if unread:
        return f"{unread} update(s) waiting"
    if active_threads:
        return f"{active_threads} active mission(s)"
    return "Ready"


def _badge(value: int) -> str:
    if value <= 0:
        return ""
    return "99+" if value > 99 else str(value)
