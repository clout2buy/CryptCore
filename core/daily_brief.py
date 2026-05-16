"""Autonomous daily brief for missions, approvals, reminders, and next moves."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import (
    connector_readiness,
    credential_vault,
    goals,
    job_queue,
    live_replay,
    monitors,
    notification_center,
    repair_doctor,
    scheduler,
    session,
    settings,
    work_threads,
)


SCHEMA_VERSION = 1
WINDOW_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class BriefItem:
    title: str
    detail: str = ""
    severity: str = "info"
    source: str = "daily-brief"
    related_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DailyBrief:
    brief_id: str
    cwd: str
    date: str
    generated_at: int
    since: int
    overnight: list[BriefItem] = field(default_factory=list)
    open_missions: list[BriefItem] = field(default_factory=list)
    approvals: list[BriefItem] = field(default_factory=list)
    reminders: list[BriefItem] = field(default_factory=list)
    next_actions: list[BriefItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("overnight", "open_missions", "approvals", "reminders", "next_actions"):
            data[key] = [item.to_dict() if isinstance(item, BriefItem) else item for item in getattr(self, key)]
        data["counts"] = {
            "overnight": len(self.overnight),
            "openMissions": len(self.open_missions),
            "approvals": len(self.approvals),
            "reminders": len(self.reminders),
            "nextActions": len(self.next_actions),
        }
        data["markdown"] = to_markdown(self)
        return data


def brief_dir(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "briefs" / "daily"


def latest_path(cwd: str | Path) -> Path:
    return brief_dir(cwd) / "latest.json"


def build(cwd: str | Path, runtime_snapshot: dict[str, Any] | None = None, *, now: int | None = None) -> DailyBrief:
    root = Path(cwd).expanduser().resolve()
    current = int(now or time.time())
    since = current - WINDOW_SECONDS
    runtime = runtime_snapshot if isinstance(runtime_snapshot, dict) else {}
    notifications = _dict(runtime.get("notifications")) or notification_center.snapshot(root)
    queue = _dict(runtime.get("jobQueue")) or job_queue.snapshot(root)
    schedule = _dict(runtime.get("missionScheduler")) or scheduler.snapshot(root)
    replay = _dict(runtime.get("liveReplay")) or live_replay.snapshot(root)
    repair = _dict(runtime.get("repairDoctor")) or repair_doctor.snapshot(root, runtime)
    connectors = _dict(runtime.get("connectorReadiness")) or connector_readiness.snapshot(root, runtime)
    credentials = _dict(runtime.get("credentialVault")) or credential_vault.snapshot(root)

    active_threads = work_threads.list_threads(root)[:8]
    active_goals = goals.list_goals(root)[:8]
    active_monitors = monitors.list_monitors(root)[:8]

    brief = DailyBrief(
        brief_id=f"brief_{_date(current).replace('-', '')}",
        cwd=str(root),
        date=_date(current),
        generated_at=current,
        since=since,
        overnight=_overnight(notifications, queue, replay, active_monitors, since),
        open_missions=_open_missions(active_threads, active_goals),
        approvals=_approvals(notifications, connectors, credentials),
        reminders=_reminders(root, schedule, active_monitors),
        next_actions=_next_actions(repair, connectors, credentials, schedule, active_threads),
    )
    return brief


def snapshot(cwd: str | Path, runtime_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    brief = build(cwd, runtime_snapshot)
    data = brief.to_dict()
    data["path"] = str(latest_path(cwd))
    return data


def write_brief(cwd: str | Path, runtime_snapshot: dict[str, Any] | None = None, *, now: int | None = None) -> dict[str, Any]:
    brief = build(cwd, runtime_snapshot, now=now)
    folder = brief_dir(cwd)
    folder.mkdir(parents=True, exist_ok=True)
    md_path = folder / f"{brief.date}.md"
    json_path = latest_path(cwd)
    md_path.write_text(to_markdown(brief), encoding="utf-8")
    json_path.write_text(json.dumps({"schema": SCHEMA_VERSION, "brief": brief.to_dict()}, indent=2, ensure_ascii=False), encoding="utf-8")
    settings.restrict_file_permissions(md_path)
    settings.restrict_file_permissions(json_path)
    data = brief.to_dict()
    data["path"] = str(md_path)
    data["latestPath"] = str(json_path)
    return data


def prompt_section(cwd: str | Path, runtime_snapshot: dict[str, Any] | None = None, *, limit: int = 5) -> str:
    brief = build(cwd, runtime_snapshot)
    items = [*brief.approvals, *brief.reminders, *brief.next_actions][: max(1, limit)]
    if not items:
        return ""
    lines = ["# Daily Brief"]
    lines.append(f"- date={brief.date}; open_missions={len(brief.open_missions)} approvals={len(brief.approvals)} reminders={len(brief.reminders)}")
    for item in items:
        lines.append(f"- {item.severity} {item.title}: {item.detail}")
    return "\n".join(lines)


def to_markdown(brief: DailyBrief) -> str:
    lines = [f"# Crypt Daily Brief - {brief.date}", ""]
    sections = [
        ("Overnight", brief.overnight),
        ("Open Missions", brief.open_missions),
        ("Approvals", brief.approvals),
        ("Reminders", brief.reminders),
        ("Next Actions", brief.next_actions),
    ]
    for title, items in sections:
        lines.append(f"## {title}")
        if not items:
            lines.append("- Clear.")
        else:
            for item in items:
                detail = f" - {item.detail}" if item.detail else ""
                lines.append(f"- **{item.title}**{detail}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _overnight(notifications: dict[str, Any], queue: dict[str, Any], replay: dict[str, Any], active_monitors: list[monitors.Monitor], since: int) -> list[BriefItem]:
    items: list[BriefItem] = []
    for note in (notifications.get("items") or [])[:6]:
        if int(note.get("created_at") or 0) >= since:
            items.append(BriefItem(str(note.get("title") or "Notification"), str(note.get("body") or ""), str(note.get("severity") or "info"), "notification", str(note.get("notification_id") or "")))
    for job in (queue.get("jobs") or [])[:5]:
        if int(job.get("updated_at") or 0) >= since and str(job.get("status") or "") in {"succeeded", "failed", "interrupted"}:
            items.append(BriefItem(str(job.get("title") or "Background job"), str(job.get("result") or job.get("status") or ""), str(job.get("status") or "info"), "job_queue", str(job.get("job_id") or "")))
    for event in (replay.get("items") or [])[:5]:
        if int(float(event.get("created_at") or 0)) >= since:
            items.append(BriefItem(str(event.get("title") or event.get("event") or "Live event"), str(event.get("text") or event.get("status") or ""), "info", "live_replay", str(event.get("replay_id") or "")))
    for monitor in active_monitors:
        if monitor.last_change_at and monitor.last_change_at >= since:
            items.append(BriefItem(monitor.title, monitor.last_value, "info", "monitor", monitor.monitor_id))
    return items[:10]


def _open_missions(active_threads: list[work_threads.WorkThread], active_goals: list[goals.Goal]) -> list[BriefItem]:
    items: list[BriefItem] = []
    for thread in active_threads[:6]:
        detail = thread.next_action or ", ".join(thread.blockers[:2]) or thread.state
        severity = "warning" if thread.state == "blocked" else "info"
        items.append(BriefItem(thread.title, detail, severity, "work_thread", thread.thread_id))
    goal_ids = {thread.goal_id for thread in active_threads}
    for goal in active_goals[:6]:
        if goal.goal_id in goal_ids:
            continue
        detail = goal.success_metric or goal.description or goal.status
        items.append(BriefItem(goal.title, detail, "info", "goal", goal.goal_id))
    return items[:10]


def _approvals(notifications: dict[str, Any], connectors: dict[str, Any], credentials: dict[str, Any]) -> list[BriefItem]:
    items: list[BriefItem] = []
    for note in notifications.get("items") or []:
        if str(note.get("status") or "") == "unread" and str(note.get("severity") or "") == "approval":
            items.append(BriefItem(str(note.get("title") or "Approval needed"), str(note.get("body") or ""), "approval", "notification", str(note.get("notification_id") or "")))
    for ref in credentials.get("references") or []:
        if str(ref.get("status") or "") == "needed":
            items.append(BriefItem(f"{ref.get('service') or 'Credential'} needed", str(ref.get("purpose") or ""), "approval", "credential", str(ref.get("ref_id") or "")))
    for card in connectors.get("cards") or []:
        if str(card.get("status") or "") == "needs-auth":
            items.append(BriefItem(f"{card.get('label') or 'Connector'} auth missing", str(card.get("setup_command") or ""), "approval", "connector", str(card.get("connector_id") or "")))
    return items[:10]


def _reminders(root: Path, schedule: dict[str, Any], active_monitors: list[monitors.Monitor]) -> list[BriefItem]:
    items: list[BriefItem] = []
    for job in (schedule.get("jobs") or [])[:8]:
        due_at = int(job.get("due_at") or 0)
        if due_at and due_at <= int(time.time()):
            detail = job.get("prompt") or job.get("cadence") or "scheduled follow-up is due"
            items.append(BriefItem(str(job.get("title") or "Scheduled follow-up"), str(detail), "warning", "scheduler", str(job.get("job_id") or "")))
    for goal in goals.due_goals(root)[:5]:
        items.append(BriefItem(goal.title, goal.success_metric or "goal review is due", "warning", "goal", goal.goal_id))
    for thread in work_threads.due_threads(root)[:5]:
        items.append(BriefItem(thread.title, thread.next_action or "thread review is due", "warning", "work_thread", thread.thread_id))
    for monitor in active_monitors[:4]:
        if not monitor.last_checked_at:
            items.append(BriefItem(monitor.title, "monitor has not been checked yet", "info", "monitor", monitor.monitor_id))
    return items[:10]


def _next_actions(
    repair: dict[str, Any],
    connectors: dict[str, Any],
    credentials: dict[str, Any],
    schedule: dict[str, Any],
    active_threads: list[work_threads.WorkThread],
) -> list[BriefItem]:
    items: list[BriefItem] = []
    if int(repair.get("failing") or 0):
        command = (repair.get("repairCommands") or ["open Settings > Repair Doctor"])[0]
        items.append(BriefItem("Repair runtime issue", str(command), "warning", "repair_doctor"))
    blocked = [thread for thread in active_threads if thread.state == "blocked"]
    if blocked:
        items.append(BriefItem("Unblock mission", blocked[0].title, "warning", "work_thread", blocked[0].thread_id))
    if int(schedule.get("due") or 0):
        items.append(BriefItem("Run due scheduled work", f"{schedule.get('due')} due / {schedule.get('overdue', 0)} overdue", "warning", "scheduler"))
    if int(credentials.get("needed") or 0):
        items.append(BriefItem("Resolve credential references", f"{credentials.get('needed')} needed", "approval", "credential"))
    if int(connectors.get("needsAuth") or 0):
        items.append(BriefItem("Configure external connector auth", f"{connectors.get('needsAuth')} connector(s) need auth", "approval", "connector"))
    if not items:
        items.append(BriefItem("Keep building", "No urgent blockers. Continue the highest priority mission or ask for a new outcome.", "info", "daily-brief"))
    return items[:8]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _date(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))
