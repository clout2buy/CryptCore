"""Visible operator HUD for browser and desktop activity."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import browser_recorder, desktop_recorder


@dataclass(frozen=True)
class OperatorChannel:
    channel: str
    status: str
    target: str = ""
    last_action: str = ""
    approval_boundary: str = ""
    recording_id: str = ""
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def snapshot(cwd: str | Path) -> dict[str, Any]:
    channels = [_browser_channel(cwd), _desktop_channel(cwd)]
    active = [channel for channel in channels if channel.status in {"running", "planned", "blocked"}]
    approval_required = [
        channel for channel in channels
        if "approval" in channel.approval_boundary.lower() and channel.status not in {"idle", "verified", "done"}
    ]
    return {
        "status": "active" if active else "idle",
        "active": len(active),
        "approvalRequired": len(approval_required),
        "channels": [channel.to_dict() for channel in channels],
    }


def prompt_section(cwd: str | Path) -> str:
    data = snapshot(cwd)
    channels = [channel for channel in data["channels"] if channel["status"] != "idle"]
    if not channels:
        return ""
    lines = ["# Operator HUD"]
    for channel in channels:
        lines.append(
            f"- {channel['channel']}: status={channel['status']}; target={channel['target'] or 'none'}; "
            f"last={channel['last_action'] or 'none'}; boundary={channel['approval_boundary']}"
        )
    return "\n".join(lines)


def _browser_channel(cwd: str | Path) -> OperatorChannel:
    rows = browser_recorder.list_recordings(cwd, include_all=True, limit=1)
    if not rows:
        return OperatorChannel(
            channel="browser",
            status="idle",
            approval_boundary="Read, inspect, and draft locally. External submits/posts/login actions require approval.",
        )
    row = rows[0]
    last_action = _last([*(row.notes or []), *(row.checks or []), *(row.console_errors or [])])
    if row.screenshots:
        last_action = last_action or f"{len(row.screenshots)} screenshot(s) captured"
    return OperatorChannel(
        channel="browser",
        status=row.status,
        target=row.url or row.title,
        last_action=last_action,
        approval_boundary="Browser can inspect and record. Posting, sending, purchasing, or account changes require approval.",
        recording_id=row.recording_id,
        updated_at=row.updated_at,
    )


def _desktop_channel(cwd: str | Path) -> OperatorChannel:
    rows = desktop_recorder.list_recordings(cwd, include_all=True, limit=1)
    if not rows:
        return OperatorChannel(
            channel="desktop",
            status="idle",
            approval_boundary="Desktop movement is visual-first; sensitive typing/clicking requires approval.",
        )
    row = rows[0]
    pending = [action for action in row.actions if action.requires_approval and not action.approved]
    latest_action = row.actions[-1] if row.actions else None
    last_action = latest_action.narration or latest_action.action if latest_action else _last(row.safety_notes)
    target = latest_action.target if latest_action else row.title
    boundary = (
        f"{len(pending)} pending approval action(s)"
        if pending or row.approval_required
        else "Approved non-sensitive desktop plan."
    )
    return OperatorChannel(
        channel="desktop",
        status="blocked" if pending else row.status,
        target=target,
        last_action=last_action,
        approval_boundary=boundary,
        recording_id=row.recording_id,
        updated_at=row.updated_at or int(time.time()),
    )


def _last(values: list[str]) -> str:
    for value in reversed(values):
        clean = " ".join(str(value or "").split())
        if clean:
            return clean[:220]
    return ""
