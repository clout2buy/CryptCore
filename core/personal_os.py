"""Personal Operating System command surface for Crypt."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import (
    artifact_studio,
    external_drafts,
    goals,
    job_queue,
    local_voice,
    memory_journal,
    notification_center,
    scheduler,
    work_threads,
)


@dataclass(frozen=True)
class OSSignal:
    label: str
    value: str
    detail: str = ""
    status: str = "ready"


@dataclass(frozen=True)
class OSLane:
    lane_id: str
    label: str
    status: str
    action: str
    count: int = 0
    detail: str = ""


@dataclass(frozen=True)
class PersonalOSSurface:
    mode: str
    command: str
    status: str
    summary: dict[str, int] = field(default_factory=dict)
    signals: list[OSSignal] = field(default_factory=list)
    lanes: list[OSLane] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build(cwd: str | Path, snapshot: dict[str, Any] | None = None) -> PersonalOSSurface:
    root = Path(cwd).expanduser().resolve()
    data = snapshot or _snapshot(root)
    threads = list(data.get("workThreads") or [])
    active_threads = [item for item in threads if str(item.get("state") or "active") not in {"completed", "cancelled"}]
    blocked_threads = [item for item in active_threads if str(item.get("state") or "") == "blocked"]
    goals_count = len(data.get("goals") or [])
    notifications = dict(data.get("notifications") or {})
    drafts = dict(data.get("externalDrafts") or {})
    jobs = dict(data.get("jobQueue") or {})
    memory = dict(data.get("memoryJournal") or {})
    artifacts = dict(data.get("artifactSummary") or {})
    voice = dict(data.get("voice") or {})
    voice_convo = dict(data.get("voiceConversation") or {})
    scheduler_data = dict(data.get("missionScheduler") or {})
    revenue_ops = dict(data.get("revenueOps") or {})
    approvals = int(drafts.get("pending") or 0)
    critical = int(notifications.get("critical") or 0)
    due = int(scheduler_data.get("due") or 0)
    running_jobs = int(jobs.get("running") or 0)
    blockers = _blockers(blocked_threads, notifications, approvals)
    status = "attention" if blockers or critical or due else ("working" if running_jobs else "ready")
    signals = [
        OSSignal("Mode", "Personal OS", "Talk normally. Crypt routes the work.", status),
        OSSignal("Missions", str(len(active_threads)), f"{len(blocked_threads)} blocked / {due} due", "attention" if blocked_threads or due else "ready"),
        OSSignal("Memory", str(memory.get("longTermCount") or 0), f"{memory.get('openLoopCount') or 0} open loop(s)", "ready"),
        OSSignal("Approvals", str(approvals), "External effects wait here.", "attention" if approvals else "ready"),
        OSSignal("Files", str(artifacts.get("total") or 0), f"{artifacts.get('verified') or 0} verified", "ready"),
        OSSignal("Voice", "ready" if voice.get("ready") else "setup", f"{voice_convo.get('status') or 'idle'} / {voice_convo.get('turnCount') or 0} turn(s)", "ready" if voice.get("ready") else "setup"),
    ]
    lanes = [
        OSLane("chat", "Chat", "ready", "Take the user's plain language and decide the route.", 1, "No starter prompts needed."),
        OSLane("missions", "Missions", "attention" if blocked_threads or due else "ready", "Create or resume durable work threads when the ask has follow-through.", len(active_threads), _first_action(active_threads)),
        OSLane("memory", "Memory", "ready", "Passively save durable preferences, projects, and open loops.", int(memory.get("longTermCount") or 0), f"{memory.get('workingCount') or 0} working signal(s)."),
        OSLane("files", "Files", "ready", "Register outputs, imports, docs, screenshots, and generated assets.", int(artifacts.get("total") or 0), f"{artifacts.get('missionLinked') or 0} mission-linked."),
        OSLane("voice", "Voice", "setup" if not voice.get("ready") else "ready", "Use speech for quick commands and replies when available.", int(voice_convo.get("turnCount") or 0), voice_convo.get("status") or "Local voice loop."),
        OSLane("business", "Business", "ready", "Track offers, content, revenue, customers, and next actions.", int(revenue_ops.get("targets") or 0), _business_detail(revenue_ops)),
        OSLane("approvals", "Approvals", "attention" if approvals else "ready", "Keep public posts, email, purchases, and account actions gated.", approvals, "Draft first, publish after approval."),
        OSLane("jobs", "Jobs", "working" if running_jobs else "ready", "Recover and display long-running background work.", running_jobs, f"{jobs.get('queued') or 0} queued."),
    ]
    next_actions = _next_actions(active_threads, notifications, due, goals_count)
    return PersonalOSSurface(
        mode="personal-os",
        command="Say what you want. Crypt handles routing, memory, missions, files, voice, approvals, and follow-through.",
        status=status,
        summary={
            "activeThreads": len(active_threads),
            "blockedThreads": len(blocked_threads),
            "goals": goals_count,
            "approvals": approvals,
            "notifications": int(notifications.get("unread") or 0),
            "due": due,
            "runningJobs": running_jobs,
        },
        signals=signals,
        lanes=lanes,
        next_actions=next_actions,
        blockers=blockers,
    )


def snapshot(cwd: str | Path, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return build(cwd, data).to_dict()


def prompt_section(cwd: str | Path, *, data: dict[str, Any] | None = None) -> str:
    surface = build(cwd, data)
    lines = [
        "# Personal OS Mode",
        f"- status={surface.status}; command={surface.command}",
        "- Do not require the user to orchestrate prompts; infer route, create missions when useful, and surface approvals only for external effects.",
    ]
    for action in surface.next_actions[:4]:
        lines.append(f"- next: {action}")
    for blocker in surface.blockers[:4]:
        lines.append(f"- blocker: {blocker}")
    return "\n".join(lines)


def _snapshot(root: Path) -> dict[str, Any]:
    studio = artifact_studio.snapshot(root)
    return {
        "goals": [asdict(goal) for goal in goals.list_goals(root, include_all=True)[:20]],
        "workThreads": [asdict(thread) for thread in work_threads.list_threads(root, include_all=True)[:20]],
        "notifications": notification_center.snapshot(root),
        "externalDrafts": external_drafts.snapshot(root),
        "jobQueue": job_queue.snapshot(root),
        "memoryJournal": memory_journal.snapshot(root),
        "artifactSummary": studio["summary"],
        "voice": local_voice.status().to_dict(),
        "missionScheduler": scheduler.snapshot(root),
        "revenueOps": {},
    }


def _blockers(blocked_threads: list[dict[str, Any]], notifications: dict[str, Any], approvals: int) -> list[str]:
    out = []
    for thread in blocked_threads[:4]:
        out.append(str(thread.get("next_action") or thread.get("title") or "Blocked thread needs attention."))
    for item in list(notifications.get("items") or [])[:4]:
        if str(item.get("severity") or "") in {"warning", "error", "approval"} and str(item.get("status") or "unread") == "unread":
            out.append(str(item.get("title") or item.get("body") or "Notification needs attention."))
    if approvals:
        out.append(f"{approvals} external draft(s) need approval before any public/send action.")
    return _dedupe(out)[:8]


def _next_actions(active_threads: list[dict[str, Any]], notifications: dict[str, Any], due: int, goals_count: int) -> list[str]:
    out = []
    for thread in active_threads[:5]:
        action = str(thread.get("next_action") or "").strip()
        if action:
            out.append(action)
    for item in list(notifications.get("items") or [])[:3]:
        title = str(item.get("title") or "").strip()
        if title:
            out.append(title)
    if due:
        out.append(f"Review {due} due scheduled mission(s).")
    if not out and not goals_count:
        out.append("Wait for the next plain-language request, then create the right mission automatically.")
    return _dedupe(out)[:8]


def _first_action(active_threads: list[dict[str, Any]]) -> str:
    for thread in active_threads:
        action = str(thread.get("next_action") or "").strip()
        if action:
            return action
    return "No active next action."


def _business_detail(revenue_ops: dict[str, Any]) -> str:
    forecast = revenue_ops.get("forecast") if isinstance(revenue_ops.get("forecast"), dict) else {}
    value = float(forecast.get("revenue30d") or 0)
    return f"30d forecast ${value:.2f}"


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(str(value or "").split())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out
