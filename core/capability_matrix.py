"""Runtime capability matrix for Crypt.

The matrix is deliberately read-only. It gives the UI and prompts a compact
view of what Crypt can already do, what is only local/planned, and what needs
setup before it can be trusted for autonomous work.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import (
    agent_profiles,
    integrations,
    local_voice,
    memory_journal,
    revenue,
    scheduler,
    skills,
)


VALID_STATUSES = {"ready", "needs-setup", "local-only", "approval-gated", "watch", "planned"}


@dataclass(frozen=True)
class Capability:
    capability_id: str
    label: str
    category: str
    status: str
    module: str
    summary: str
    evidence: str = ""
    next_action: str = ""
    risk: str = "low"
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = data.pop("capability_id")
        return data


@dataclass(frozen=True)
class CapabilityMatrix:
    workspace: str
    total: int
    ready: int
    needs_setup: int
    approval_gated: int
    capabilities: tuple[Capability, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "total": self.total,
            "ready": self.ready,
            "needsSetup": self.needs_setup,
            "approvalGated": self.approval_gated,
            "capabilities": [capability.to_dict() for capability in self.capabilities],
        }


def build(cwd: str | Path, snapshot: dict[str, Any] | None = None) -> CapabilityMatrix:
    root = Path(cwd).expanduser().resolve()
    data = snapshot or {}
    caps = tuple(_capabilities(root, data))
    return CapabilityMatrix(
        workspace=str(root),
        total=len(caps),
        ready=sum(1 for item in caps if item.status == "ready"),
        needs_setup=sum(1 for item in caps if item.status == "needs-setup"),
        approval_gated=sum(1 for item in caps if item.status == "approval-gated"),
        capabilities=caps,
    )


def prompt_section(cwd: str | Path, *, limit: int = 12) -> str:
    matrix = build(cwd)
    lines = ["# Capability Matrix"]
    for capability in matrix.capabilities[: max(1, limit)]:
        lines.append(
            f"- {capability.label}: {capability.status}; module={capability.module}; {capability.summary}"
        )
    return "\n".join(lines)


def _capabilities(root: Path, snapshot: dict[str, Any]) -> list[Capability]:
    memory = _value(snapshot, "memoryJournal", lambda: memory_journal.snapshot(root), {})
    voice = _value(snapshot, "voice", lambda: local_voice.status().to_dict(), {})
    integration_cards = _value(snapshot, "integrationsPreview", integrations.snapshot, [])
    profiles = _value(snapshot, "agentProfiles", lambda: [item.to_dict() for item in agent_profiles.list_profiles(root)], [])
    skill_cards = _value(snapshot, "skillsPreview", lambda: [item.as_dict() for item in skills.discover(root, include_disabled=True)], [])
    threads = _value(snapshot, "workThreads", lambda: [], [])
    routes = snapshot.get("routes") if isinstance(snapshot.get("routes"), list) else []
    providers = snapshot.get("providers") if isinstance(snapshot.get("providers"), list) else []
    release_plan = root / ".crypt" / "release" / "release-checklist.md"
    bench_suite = root / "benchmarks" / "agent_core.json"
    webui = snapshot.get("webui") if isinstance(snapshot.get("webui"), dict) else {}
    remote_access = snapshot.get("remoteAccess") if isinstance(snapshot.get("remoteAccess"), dict) else {}
    revenue_snapshot = _value(snapshot, "revenue", lambda: revenue.dashboard_snapshot(root), {})
    schedules = _value(snapshot, "schedulesPreview", lambda: [asdict_compat(item) for item in scheduler.list_jobs(root, include_all=True)], [])

    enabled_integrations = [item for item in integration_cards if item.get("enabled")]
    configured_integrations = [item for item in integration_cards if item.get("configured")]
    active_threads = [
        item for item in threads
        if str(item.get("state") or item.get("status") or "active") not in {"completed", "cancelled"}
    ]
    revenue_summary = revenue_snapshot.get("summary") if isinstance(revenue_snapshot, dict) else {}

    return [
        _cap(
            "chat-runtime",
            "Chat Runtime",
            "core",
            "ready" if snapshot.get("authOk", True) else "needs-setup",
            "core.app_daemon",
            "Main conversation loop with provider/model routing and live event output.",
            evidence=f"{len(providers)} provider(s), {len(routes)} route(s)",
            next_action="Use normal chat; Crypt chooses the route unless pinned.",
            signals={"provider": snapshot.get("provider"), "model": snapshot.get("model")},
        ),
        _cap(
            "live-events",
            "Live Thinking And Tool Calls",
            "core",
            "ready",
            "core.live_events",
            "Typed event stream for thinking, tools, approvals, browser, desktop, and mission updates.",
            evidence="WebUI polls /api/events and patches live rows by key.",
        ),
        _cap(
            "passive-memory",
            "Passive Memory",
            "knowledge",
            "ready",
            "core.memory_journal",
            "Learns useful facts from normal conversation without a special remember command.",
            evidence=f"{memory.get('longTermCount', 0)} long-term, {memory.get('workingCount', 0)} working",
            next_action="Keep talking naturally; durable facts are scored and saved.",
            signals=memory,
        ),
        _cap(
            "mission-brain",
            "Mission Brain",
            "autonomy",
            "ready",
            "core.mission_router/core.work_threads",
            "Turns bigger goals into durable work threads with state, next actions, and blockers.",
            evidence=f"{len(active_threads)} active thread(s)",
            next_action="Say the desired outcome; Crypt should create or update the mission.",
        ),
        _cap(
            "agent-profiles",
            "Reusable Agents",
            "autonomy",
            "ready" if profiles else "needs-setup",
            "core.agent_profiles/core.agent_delegation",
            "Saved specialist agents with model/provider preferences and delegation hints.",
            evidence=f"{len(profiles)} saved profile(s)",
            next_action="Ask for a specialist once; Crypt can save and reuse it.",
            risk="medium",
        ),
        _cap(
            "local-skills",
            "Local Skills",
            "knowledge",
            "ready" if skill_cards else "needs-setup",
            "core.skills/core.skill_forge",
            "Filesystem-native SKILL.md instructions that Crypt can discover and apply.",
            evidence=f"{len(skill_cards)} visible skill(s)",
            next_action="Repeated successful workflows should become skills.",
        ),
        _cap(
            "voice-loop",
            "Voice Input And TTS",
            "interface",
            "ready" if voice.get("ready") else "needs-setup",
            "core.local_voice",
            "Browser speech-to-text plus local Kokoro text-to-speech with selectable voices.",
            evidence="ready" if voice.get("ready") else ", ".join(voice.get("missing") or ["voice setup missing"]),
            next_action="Run the voice setup script if local assets are missing.",
            risk="low",
        ),
        _cap(
            "browser-operator",
            "Visual Browser Operator",
            "operation",
            "approval-gated",
            "core.browser_operator",
            "Plans browser browsing, screenshots, form interaction, and visual QA with external-action gates.",
            evidence="local browser lane available",
            next_action="Use visual evidence before acting on external sites.",
            risk="medium",
        ),
        _cap(
            "desktop-operator",
            "Desktop Operator",
            "operation",
            "approval-gated",
            "core.desktop_operator",
            "Plans mouse, keyboard, screenshot, and visible desktop actions with sensitive-action approval.",
            evidence="visual desktop planner available",
            next_action="Keep destructive or account actions gated.",
            risk="high",
        ),
        _cap(
            "business-ledger",
            "Business And Revenue Ledger",
            "business",
            "ready",
            "core.revenue/core.business_mission",
            "Tracks revenue, expenses, visits, leads, conversions, channels, and business mission context.",
            evidence=f"${revenue_summary.get('revenue', 0)} revenue, {revenue_summary.get('leads', 0)} lead(s)",
            next_action="Log events or launch a business mission from chat.",
        ),
        _cap(
            "external-integrations",
            "External Integrations",
            "connectors",
            "ready" if configured_integrations else "needs-setup",
            "core.integrations",
            "Registry for GitHub, email, calendar, storage, social, payments, analytics, and databases.",
            evidence=f"{len(configured_integrations)} configured, {len(enabled_integrations)} enabled",
            next_action="Connect only the services Crypt should use; sends/posts stay approval gated.",
            risk="high",
        ),
        _cap(
            "scheduler-monitors",
            "Schedulers And Monitors",
            "autonomy",
            "ready",
            "core.scheduler/core.monitors",
            "Keeps follow-ups, recurring checks, and read-only monitors tied to goals and threads.",
            evidence=f"{len(schedules)} scheduled job(s)",
            next_action="Attach cadence when a mission needs follow-up.",
        ),
        _cap(
            "remote-webui",
            "Remote WebUI Access",
            "interface",
            "ready" if not remote_access.get("remote") else "approval-gated",
            "core.webui_access/core.webui_backup",
            "Local-first UI with optional token-protected remote mode and non-secret backup/restore.",
            evidence=webui.get("url") or "local server",
            next_action="Use a token before binding to remote hosts.",
            risk="medium",
        ),
        _cap(
            "benchmark-suite",
            "Agent Benchmark Suite",
            "verification",
            "ready" if bench_suite.exists() else "needs-setup",
            "core.bench",
            "Runs repeatable agent-core checks across chat, code, research, browser, memory, tools, and UI.",
            evidence=str(bench_suite) if bench_suite.exists() else "benchmarks/agent_core.json missing",
            next_action="Run the suite before major release claims.",
        ),
        _cap(
            "release-train",
            "Release Train",
            "verification",
            "ready" if release_plan.exists() else "local-only",
            "core.release_train",
            "Generates release checklist, verification status, git snapshot, risks, and rollback notes.",
            evidence=str(release_plan) if release_plan.exists() else "release checklist has not been generated yet",
            next_action="Run `python main.py release` before release packaging.",
        ),
    ]


def _cap(
    capability_id: str,
    label: str,
    category: str,
    status: str,
    module: str,
    summary: str,
    *,
    evidence: str = "",
    next_action: str = "",
    risk: str = "low",
    signals: dict[str, Any] | None = None,
) -> Capability:
    clean_status = status if status in VALID_STATUSES else "watch"
    return Capability(
        capability_id=capability_id,
        label=label,
        category=category,
        status=clean_status,
        module=module,
        summary=summary,
        evidence=evidence,
        next_action=next_action,
        risk=risk,
        signals=signals or {},
    )


def _value(
    snapshot: dict[str, Any],
    key: str,
    fallback: Callable[[], Any],
    default: Any,
) -> Any:
    if key in snapshot:
        return snapshot.get(key) if snapshot.get(key) is not None else default
    try:
        return fallback()
    except Exception:
        return default


def asdict_compat(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return value
    return {}
