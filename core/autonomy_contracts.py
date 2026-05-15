"""Named autonomy contracts for different kinds of work.

Contracts keep Crypt assertive without becoming reckless. They describe what is
safe to do immediately, what should become a mission, and what must be drafted
for approval before it affects the outside world.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from . import intent_router


@dataclass(frozen=True)
class AutonomyContract:
    profile_id: str
    label: str
    intents: tuple[str, ...]
    autonomy_level: str
    default_action: str
    allowed_without_approval: tuple[str, ...] = ()
    approval_required: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    memory_policy: str = ""
    mission_policy: str = ""
    agent_policy: str = ""
    tone: str = "direct, warm, no robotic filler"
    risk: str = "low"
    ui_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = data.pop("profile_id")
        return data


CONTRACTS: tuple[AutonomyContract, ...] = (
    AutonomyContract(
        profile_id="casual-chat",
        label="Casual Chat",
        intents=("conversation", "empty"),
        autonomy_level="low",
        default_action="converse",
        allowed_without_approval=(
            "answer naturally",
            "remember stable user preferences",
            "suggest one useful next step when obvious",
        ),
        approval_required=("none unless tools or external effects are introduced",),
        memory_policy="Save durable preferences, interests, tone feedback, and open loops. Ignore throwaway small talk.",
        mission_policy="Do not create a mission unless the user asks for an outcome that needs follow-through.",
        agent_policy="Do not create specialists for normal chat.",
        ui_summary="Talk like a real assistant and quietly learn durable preferences.",
    ),
    AutonomyContract(
        profile_id="build-work",
        label="Build Work",
        intents=("code", "file", "review", "learn", "general_task"),
        autonomy_level="high",
        default_action="execute",
        allowed_without_approval=(
            "inspect project files",
            "edit workspace files",
            "run focused checks",
            "create local artifacts",
            "update memory and skills from repeated wins",
        ),
        approval_required=("destructive git operations", "external network writes", "credential use"),
        forbidden=("revert user changes without explicit request", "delete unrelated files"),
        memory_policy="Save project preferences, repeated implementation patterns, test commands, and user corrections.",
        mission_policy="Create or update a work thread when the task spans multiple steps or needs follow-up.",
        agent_policy="Create/reuse builder, reviewer, or frontend specialists when it reduces repeated orchestration.",
        risk="medium",
        ui_summary="Inspect, patch, test, and keep the work moving inside the local workspace.",
    ),
    AutonomyContract(
        profile_id="business-ops",
        label="Business Ops",
        intents=("business", "schedule"),
        autonomy_level="high",
        default_action="execute-local",
        allowed_without_approval=(
            "create business plans",
            "build local sites and dashboards",
            "track revenue/expenses/leads",
            "schedule follow-ups",
            "draft outreach and content",
        ),
        approval_required=("send messages", "publish posts", "spend money", "create accounts", "use payment systems"),
        forbidden=("misrepresent identity", "promise results without evidence", "store raw credentials"),
        memory_policy="Save offers, audiences, channels, customer facts, revenue assumptions, and launch decisions.",
        mission_policy="Always create durable missions for business launches, revenue tracking, or recurring operations.",
        agent_policy="Create/reuse growth, finance, research, and content specialists as needed.",
        risk="high",
        ui_summary="Turn business goals into missions, assets, metrics, drafts, and follow-up loops.",
    ),
    AutonomyContract(
        profile_id="browser-operation",
        label="Browser Operation",
        intents=("browser", "research"),
        autonomy_level="medium",
        default_action="operate-visually",
        allowed_without_approval=(
            "open pages",
            "read public pages",
            "capture screenshots",
            "summarize sources",
            "draft form entries",
        ),
        approval_required=("submit forms", "log in", "post content", "purchase", "change account settings"),
        forbidden=("bypass paywalls or access controls", "hide automation from required disclosure"),
        memory_policy="Save useful sources, login requirements without secrets, and successful browser workflows.",
        mission_policy="Create a monitor or research thread when the user wants recurring watch work.",
        agent_policy="Use research/browser specialists for multi-source work or visual QA.",
        risk="medium",
        ui_summary="Browse visually, gather evidence, and gate anything that changes external state.",
    ),
    AutonomyContract(
        profile_id="desktop-operation",
        label="Desktop Operation",
        intents=("desktop",),
        autonomy_level="medium",
        default_action="operate-visually",
        allowed_without_approval=("inspect visible screen", "move pointer", "capture screenshots", "draft local actions"),
        approval_required=("type into sensitive fields", "click destructive controls", "install/uninstall", "send/post/pay"),
        forbidden=("operate hidden windows blindly", "continue if the visible target is uncertain"),
        memory_policy="Save repeatable local workflows and visual landmarks, never raw secrets shown on screen.",
        mission_policy="Attach desktop operation logs to the current work thread.",
        agent_policy="Use a desktop specialist when repeated visible operation is needed.",
        risk="high",
        ui_summary="Operate the visible desktop with narration, screenshots, and explicit sensitive-action gates.",
    ),
    AutonomyContract(
        profile_id="external-action",
        label="External Action",
        intents=("external_action",),
        autonomy_level="draft-only",
        default_action="approval-gate",
        allowed_without_approval=(
            "prepare drafts",
            "check risks",
            "preview exact outgoing content",
            "record an approval request",
        ),
        approval_required=("all sends", "all posts", "all purchases", "all account creation", "all credential use"),
        forbidden=("send without approval", "post without approval", "spend without approval", "store raw secrets"),
        memory_policy="Save approved external-action preferences and denied-action reasons.",
        mission_policy="Create a mission or draft queue entry for every meaningful external action.",
        agent_policy="Use specialists to draft and review, but not to bypass approval.",
        risk="critical",
        ui_summary="Draft everything, show the exact external effect, and wait for approval.",
    ),
)


def all_profiles() -> list[AutonomyContract]:
    return list(CONTRACTS)


def select(text: str = "", route: intent_router.IntentRoute | None = None) -> AutonomyContract:
    chosen = route or intent_router.route(text)
    for profile in CONTRACTS:
        if chosen.intent in profile.intents:
            return profile
    return _profile("build-work")


def snapshot(text: str = "", route: intent_router.IntentRoute | None = None) -> dict[str, Any]:
    selected = select(text, route) if text or route else _profile("casual-chat")
    return {
        "selected": selected.to_dict(),
        "profiles": [profile.to_dict() for profile in CONTRACTS],
    }


def prompt_hint(profile: AutonomyContract) -> str:
    allowed = ", ".join(profile.allowed_without_approval[:4])
    approvals = ", ".join(profile.approval_required[:4])
    forbidden = ", ".join(profile.forbidden[:3])
    parts = [
        f"autonomy_contract={profile.profile_id}",
        f"autonomy_level={profile.autonomy_level}",
        f"default_action={profile.default_action}",
        f"allowed_without_approval={allowed}",
        f"approval_required={approvals}",
        f"memory_policy={profile.memory_policy}",
        f"mission_policy={profile.mission_policy}",
        f"agent_policy={profile.agent_policy}",
        f"tone={profile.tone}",
    ]
    if forbidden:
        parts.append(f"forbidden={forbidden}")
    return "; ".join(parts)


def prompt_section(text: str = "", route: intent_router.IntentRoute | None = None) -> str:
    profile = select(text, route)
    return "# Autonomy Contract\n" + prompt_hint(profile)


def _profile(profile_id: str) -> AutonomyContract:
    for profile in CONTRACTS:
        if profile.profile_id == profile_id:
            return profile
    return CONTRACTS[0]
