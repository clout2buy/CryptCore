"""Unified notification feed for approvals, failures, reminders, and results."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import settings


SCHEMA_VERSION = 1
VISIBLE_STATUSES = {"unread", "read", "archived"}


@dataclass(frozen=True)
class Notification:
    notification_id: str
    cwd: str
    kind: str
    title: str
    body: str = ""
    severity: str = "info"
    status: str = "unread"
    source: str = "runtime"
    related_id: str = ""
    created_at: int = 0


def notifications_path() -> Path:
    return settings.APP_DIR / "notifications.json"


def add(
    cwd: str | Path,
    kind: str,
    title: str,
    *,
    body: str = "",
    severity: str = "info",
    source: str = "runtime",
    related_id: str = "",
) -> Notification:
    root = Path(cwd).expanduser().resolve()
    item = Notification(
        notification_id="note_" + uuid.uuid4().hex[:12],
        cwd=str(root),
        kind=_clean(kind, 80) or "event",
        title=_clean(title, 160) or "Notification",
        body=_clean(body, 800),
        severity=_severity(severity),
        status="unread",
        source=_clean(source, 80) or "runtime",
        related_id=_clean(related_id, 120),
        created_at=int(time.time()),
    )
    existing = list_notifications(include_archived=True)
    _write([item, *existing[:499]])
    return item


def mark_read(notification_id: str, *, archived: bool = False) -> Notification:
    status = "archived" if archived else "read"
    return _replace(notification_id, status=status)


def list_notifications(
    cwd: str | Path | None = None,
    *,
    include_archived: bool = False,
    limit: int = 80,
) -> list[Notification]:
    root = str(Path(cwd).expanduser().resolve()) if cwd else ""
    items = _read()
    if root:
        items = [item for item in items if item.cwd == root]
    if not include_archived:
        items = [item for item in items if item.status != "archived"]
    items.sort(key=lambda item: item.created_at, reverse=True)
    return items[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    items = list_notifications(cwd, limit=60)
    unread = [item for item in items if item.status == "unread"]
    critical = [item for item in unread if item.severity in {"warning", "error", "approval"}]
    return {
        "total": len(items),
        "unread": len(unread),
        "critical": len(critical),
        "items": [asdict(item) for item in items],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    items = [item for item in list_notifications(cwd, limit=limit) if item.status == "unread"]
    if not items:
        return ""
    lines = ["# Notification Center"]
    for item in items[: max(1, limit)]:
        lines.append(f"- {item.severity} {item.kind}: {item.title} ({item.source})")
    return "\n".join(lines)


def _replace(notification_id: str, **values: Any) -> Notification:
    items = list_notifications(include_archived=True, limit=500)
    out: list[Notification] = []
    updated: Notification | None = None
    for item in items:
        if item.notification_id != notification_id:
            out.append(item)
            continue
        data = asdict(item)
        if "status" in values:
            status = str(values["status"] or "").lower()
            if status not in VISIBLE_STATUSES:
                raise ValueError(f"unknown notification status: {status}")
            data["status"] = status
        updated = Notification(**data)
        out.append(updated)
    if updated is None:
        raise KeyError(f"notification not found: {notification_id}")
    _write(out)
    return updated


def _read() -> list[Notification]:
    path = notifications_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[Notification] = []
    for item in data.get("notifications", []):
        if not isinstance(item, dict):
            continue
        try:
            status = str(item.get("status") or "unread")
            if status not in VISIBLE_STATUSES:
                status = "unread"
            out.append(
                Notification(
                    notification_id=str(item.get("notification_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    kind=str(item.get("kind") or "event"),
                    title=str(item.get("title") or ""),
                    body=str(item.get("body") or ""),
                    severity=_severity(str(item.get("severity") or "info")),
                    status=status,
                    source=str(item.get("source") or "runtime"),
                    related_id=str(item.get("related_id") or ""),
                    created_at=int(item.get("created_at") or 0),
                )
            )
        except Exception:
            continue
    return [item for item in out if item.notification_id and item.title]


def _write(items: list[Notification]) -> None:
    path = notifications_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "notifications": [asdict(item) for item in items]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _severity(value: str) -> str:
    clean = str(value or "info").strip().lower()
    return clean if clean in {"info", "success", "warning", "error", "approval"} else "info"


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
