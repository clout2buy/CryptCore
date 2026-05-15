"""Read-only monitor framework for scheduled mission checks."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import evidence, goals, settings, work_threads


SCHEMA_VERSION = 1
STATUSES = {"active", "paused", "disabled"}


@dataclass(frozen=True)
class Monitor:
    monitor_id: str
    cwd: str
    title: str
    kind: str
    target: str
    status: str = "active"
    cadence: str = ""
    goal_id: str = ""
    thread_id: str = ""
    last_value: str = ""
    last_hash: str = ""
    last_checked_at: int = 0
    last_change_at: int = 0
    created_at: int = 0
    updated_at: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class MonitorCheck:
    monitor_id: str
    title: str
    changed: bool
    value: str
    summary: str


def monitors_path() -> Path:
    return settings.APP_DIR / "monitors" / "monitors.json"


def add_monitor(
    cwd: str | Path,
    title: str,
    *,
    kind: str,
    target: str,
    cadence: str = "",
    goal_id: str = "",
    thread_id: str = "",
    baseline: str = "",
) -> Monitor:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    value_hash = _hash(baseline) if baseline else ""
    monitor = Monitor(
        monitor_id="mon_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        title=_clean(title),
        kind=_clean(kind, 80).lower(),
        target=_clean(target, 1_000),
        status="active",
        cadence=_clean(cadence, 80),
        goal_id=_clean(goal_id, 80),
        thread_id=_clean(thread_id, 80),
        last_value=_clean(baseline, 2_000),
        last_hash=value_hash,
        created_at=now,
        updated_at=now,
        history=[_history("created", "monitor created", now)],
    )
    jobs = list_monitors(include_all=True)
    jobs.append(monitor)
    _write(jobs)
    return monitor


def list_monitors(cwd: str | Path | None = None, *, include_all: bool = False) -> list[Monitor]:
    root = str(Path(cwd).expanduser().resolve()) if cwd else ""
    monitors = _read()
    if not include_all:
        monitors = [monitor for monitor in monitors if monitor.status == "active"]
    if root:
        monitors = [monitor for monitor in monitors if monitor.cwd == root]
    monitors.sort(key=lambda monitor: monitor.updated_at, reverse=True)
    return monitors


def run_monitors(
    cwd: str | Path,
    *,
    probe_values: dict[str, str] | None = None,
    limit: int = 20,
) -> list[MonitorCheck]:
    root = Path(cwd).expanduser().resolve()
    results: list[MonitorCheck] = []
    for monitor in list_monitors(root)[: max(1, limit)]:
        results.append(check_monitor(root, monitor, probe_values=probe_values or {}))
    return results


def check_monitor(
    cwd: str | Path,
    monitor: Monitor,
    *,
    probe_values: dict[str, str] | None = None,
) -> MonitorCheck:
    root = Path(cwd).expanduser().resolve()
    value = _read_value(root, monitor, probe_values or {})
    value_hash = _hash(value)
    changed = bool(monitor.last_hash and value_hash != monitor.last_hash)
    summary = (
        f"Monitor changed: {monitor.title}"
        if changed
        else f"Monitor checked: {monitor.title}"
    )
    updated = _replace_monitor(
        monitor.monitor_id,
        cwd=root,
        last_value=value,
        last_hash=value_hash,
        last_checked_at=_now(),
        last_change_at=_now() if changed else monitor.last_change_at,
        note=summary,
    )
    if changed:
        _record_change(updated, summary)
    return MonitorCheck(
        monitor_id=monitor.monitor_id,
        title=monitor.title,
        changed=changed,
        value=value,
        summary=summary,
    )


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    monitors = list_monitors(cwd)[: max(1, limit)]
    if not monitors:
        return ""
    lines = ["# Monitors"]
    for monitor in monitors:
        lines.append(f"- {monitor.kind} {monitor.title}: {monitor.target}")
    return "\n".join(lines)


def _record_change(monitor: Monitor, summary: str) -> None:
    evidence.record(
        "monitor",
        "monitor-framework",
        summary,
        details={"monitor": asdict(monitor)},
        task_id=monitor.thread_id or monitor.monitor_id,
    )
    if monitor.goal_id:
        try:
            goals.update_goal(monitor.goal_id, last_result=summary)
        except Exception:
            pass
    if monitor.thread_id:
        try:
            work_threads.update_thread(
                monitor.thread_id,
                last_note=summary,
                source="monitor-framework",
            )
        except Exception:
            pass


def _read_value(root: Path, monitor: Monitor, probe_values: dict[str, str]) -> str:
    if monitor.kind == "mock":
        return _clean(probe_values.get(monitor.target, monitor.last_value), 2_000)
    if monitor.kind == "file":
        path = Path(monitor.target)
        target = (root / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return "outside-workspace"
        if not target.exists():
            return "missing"
        if target.is_dir():
            return "directory"
        try:
            return _hash_bytes(target.read_bytes())
        except OSError as exc:
            return f"error:{type(exc).__name__}"
    return _clean(probe_values.get(monitor.target, monitor.last_value), 2_000)


def _replace_monitor(monitor_id: str, *, cwd: str | Path, note: str = "", **values: Any) -> Monitor:
    root = Path(cwd).expanduser().resolve()
    monitors = list_monitors(include_all=True)
    now = _now()
    out: list[Monitor] = []
    updated: Monitor | None = None
    for monitor in monitors:
        if monitor.monitor_id != monitor_id:
            out.append(monitor)
            continue
        data = asdict(monitor)
        for key in ("title", "kind", "target", "cadence", "goal_id", "thread_id", "last_value", "last_hash"):
            if key in values and values[key] is not None:
                data[key] = _clean(str(values[key]), 2_000)
        for key in ("last_checked_at", "last_change_at"):
            if key in values and values[key] is not None:
                data[key] = int(values[key])
        if "status" in values and values["status"] is not None:
            status = str(values["status"]).strip().lower()
            if status not in STATUSES:
                raise ValueError(f"unknown monitor status: {status}")
            data["status"] = status
        data["cwd"] = str(root)
        data["updated_at"] = now
        if note:
            data["history"] = [_history("monitor", note, now), *monitor.history[:20]]
        updated = Monitor(**data)
        out.append(updated)
    if updated is None:
        raise KeyError(f"monitor not found: {monitor_id}")
    _write(out)
    return updated


def _read() -> list[Monitor]:
    path = monitors_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[Monitor] = []
    for item in data.get("monitors", []):
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                Monitor(
                    monitor_id=str(item.get("monitor_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    title=str(item.get("title") or ""),
                    kind=str(item.get("kind") or ""),
                    target=str(item.get("target") or ""),
                    status=str(item.get("status") or "active"),
                    cadence=str(item.get("cadence") or ""),
                    goal_id=str(item.get("goal_id") or ""),
                    thread_id=str(item.get("thread_id") or ""),
                    last_value=str(item.get("last_value") or ""),
                    last_hash=str(item.get("last_hash") or ""),
                    last_checked_at=int(item.get("last_checked_at") or 0),
                    last_change_at=int(item.get("last_change_at") or 0),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                    history=[entry for entry in item.get("history", []) if isinstance(entry, dict)],
                )
            )
        except Exception:
            continue
    return [monitor for monitor in out if monitor.monitor_id and monitor.title]


def _write(monitors: list[Monitor]) -> None:
    path = monitors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "monitors": [asdict(monitor) for monitor in monitors]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _hash(value: str) -> str:
    return _hash_bytes(str(value or "").encode("utf-8", errors="replace"))


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha1(value).hexdigest()


def _history(source: str, text: str, now: int) -> dict[str, Any]:
    return {"source": source, "text": _clean(text, 500), "at": now}


def _clean(value: str, limit: int = 500) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
