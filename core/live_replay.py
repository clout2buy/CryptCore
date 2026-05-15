"""Persistent replay log for live tool, browser, desktop, and command events."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import redact, session, settings


REPLAY_EVENTS = {
    "toolCall",
    "toolStarted",
    "toolProgress",
    "toolResult",
    "commandResult",
    "browserActivity",
    "desktopActivity",
    "missionStep",
    "approvalRequested",
    "approvalResolved",
}


@dataclass(frozen=True)
class ReplayItem:
    replay_id: str
    event: str
    seq: int
    title: str
    text: str = ""
    status: str = ""
    session_key: str = ""
    call_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def replay_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "live_replay" / "events.jsonl"


def record_event(cwd: str | Path, event: dict) -> ReplayItem | None:
    name = str(event.get("event") or "")
    if name not in REPLAY_EVENTS:
        return None
    seq = int(event.get("seq") or 0)
    item = ReplayItem(
        replay_id=f"replay_{seq:08d}_{name}",
        event=name,
        seq=seq,
        title=_title(event),
        text=_clean(str(event.get("text") or event.get("error") or event.get("question") or ""), 1_000),
        status=_clean(str(event.get("status") or ("ok" if event.get("ok") is True else "failed" if event.get("ok") is False else "")), 60),
        session_key=_clean(str(event.get("sessionKey") or ""), 80),
        call_id=_clean(str(event.get("callId") or event.get("approvalId") or event.get("id") or ""), 120),
        metadata=_metadata(event),
        created_at=float(event.get("ts") or time.time()),
    )
    path = replay_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
    settings.restrict_file_permissions(path)
    return item


def list_items(cwd: str | Path, *, limit: int = 80, event: str = "") -> list[ReplayItem]:
    rows = _read(cwd)
    if event:
        rows = [row for row in rows if row.event == event]
    rows.sort(key=lambda row: row.seq, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_items(cwd, limit=80)
    return {
        "total": len(rows),
        "tools": sum(1 for row in rows if row.event.startswith("tool")),
        "browser": sum(1 for row in rows if row.event == "browserActivity"),
        "desktop": sum(1 for row in rows if row.event == "desktopActivity"),
        "approvals": sum(1 for row in rows if row.event.startswith("approval")),
        "items": [row.to_dict() for row in rows[:20]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 6) -> str:
    rows = list_items(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Live Replay"]
    for row in rows:
        lines.append(f"- {row.event}/{row.status or 'event'}: {row.title}; {row.text[:220]}")
    return "\n".join(lines)


def _read(cwd: str | Path) -> list[ReplayItem]:
    path = replay_path(cwd)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows = []
    seen: set[str] = set()
    for line in reversed(lines[-300:]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        try:
            item = ReplayItem(
                replay_id=str(data.get("replay_id") or ""),
                event=str(data.get("event") or ""),
                seq=int(data.get("seq") or 0),
                title=str(data.get("title") or ""),
                text=str(data.get("text") or ""),
                status=str(data.get("status") or ""),
                session_key=str(data.get("session_key") or ""),
                call_id=str(data.get("call_id") or ""),
                metadata=dict(data.get("metadata") or {}),
                created_at=float(data.get("created_at") or 0.0),
            )
        except Exception:
            continue
        if item.replay_id in seen:
            continue
        seen.add(item.replay_id)
        rows.append(item)
    return rows


def _title(event: dict) -> str:
    if event.get("tool"):
        return f"{event.get('tool')}"
    if event.get("command"):
        return str(event.get("command"))
    if event.get("url"):
        return str(event.get("url"))
    if event.get("action"):
        return str(event.get("action"))
    return str(event.get("event") or "event")


def _metadata(event: dict) -> dict[str, Any]:
    allowed = {}
    for key in ("tool", "args", "command", "url", "action", "danger", "reason", "ok"):
        if key in event:
            allowed[key] = redact.content(event[key])
    return allowed


def _clean(value: str, limit: int) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
