"""Reusable multi-agent team templates."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import agent_profiles, multi_agent_threads, settings


@dataclass(frozen=True)
class TeamMemberTemplate:
    name: str
    purpose: str
    agent_type: str
    responsibility: str
    tools: tuple[str, ...] = ()
    write_scope: tuple[str, ...] = ()
    routing_hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentTeamTemplate:
    template_id: str
    label: str
    category: str
    summary: str
    members: tuple[TeamMemberTemplate, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "id": self.template_id,
            "members": [asdict(member) for member in self.members],
        }


TEMPLATES: tuple[AgentTeamTemplate, ...] = (
    AgentTeamTemplate(
        "business-launch",
        "Business Launch Team",
        "business",
        "Offer, site, content, revenue ops, and approval-gated launch work.",
        (
            TeamMemberTemplate("Growth Operator", "Find customers, channels, and launch angles.", "worker", "Own acquisition research and outreach drafts.", ("web_search",), ("business/research.md",), ("business", "growth", "customers")),
            TeamMemberTemplate("Frontend Builder", "Build polished launch assets and landing pages.", "worker", "Own landing page implementation and visual polish.", ("write_file", "edit_file"), ("site/", "core/webui_static/"), ("frontend", "landing", "conversion")),
            TeamMemberTemplate("Revenue Operator", "Track revenue, expenses, leads, and operations.", "planner", "Own revenue dashboard setup and recurring follow-up.", ("scheduler", "monitors"), ("business/revenue.md",), ("revenue", "ops")),
        ),
    ),
    AgentTeamTemplate(
        "frontend-build",
        "Frontend Build Team",
        "software",
        "Design direction, implementation, visual QA, and final polish.",
        (
            TeamMemberTemplate("UI Architect", "Set visual direction and interaction model.", "planner", "Own UX structure and design constraints.", ("read_file",), ("docs/frontend-plan.md",), ("frontend", "design")),
            TeamMemberTemplate("Interface Builder", "Implement the UI with scoped patches.", "worker", "Own frontend code changes.", ("edit_file", "write_file"), ("core/webui_static/",), ("frontend", "implementation")),
            TeamMemberTemplate("Visual QA", "Check screenshots, responsive behavior, console errors, and polish.", "verifier", "Own browser QA notes and regression checks.", ("browser",), ("docs/visual-qa.md",), ("qa", "browser")),
        ),
    ),
    AgentTeamTemplate(
        "bug-fix",
        "Bug Fix Team",
        "software",
        "Reproduce, patch, test, and review a bug without unrelated churn.",
        (
            TeamMemberTemplate("Bug Reproducer", "Reproduce failures and isolate cause.", "explorer", "Own reproduction notes.", ("shell", "read_file"), ("docs/repro.md",), ("debug", "reproduce")),
            TeamMemberTemplate("Patch Worker", "Patch the bug in the smallest safe scope.", "worker", "Own implementation patch.", ("edit_file",), ("core/",), ("bug", "patch")),
            TeamMemberTemplate("Regression Reviewer", "Run focused tests and inspect risk.", "verifier", "Own verification and regression notes.", ("shell",), ("docs/regression.md",), ("tests", "review")),
        ),
    ),
    AgentTeamTemplate(
        "research",
        "Research Team",
        "research",
        "Gather sources, compare claims, and produce cited decisions.",
        (
            TeamMemberTemplate("Research Scout", "Find and summarize primary sources.", "explorer", "Own source collection.", ("web_search", "fetch_url"), ("research/sources.md",), ("research", "sources")),
            TeamMemberTemplate("Synthesis Planner", "Turn findings into options and recommendations.", "planner", "Own synthesis and decision frame.", ("read_file",), ("research/synthesis.md",), ("synthesis",)),
        ),
    ),
    AgentTeamTemplate(
        "release",
        "Release Team",
        "verification",
        "Checklist, tests, screenshots, risk review, and release notes.",
        (
            TeamMemberTemplate("Verifier", "Run checks and collect failures.", "verifier", "Own verification commands and report.", ("shell",), ("docs/checks.md",), ("release", "tests")),
            TeamMemberTemplate("Risk Reviewer", "Review diff risk and rollback plan.", "release_reviewer", "Own release risk notes.", ("read_file",), ("docs/release-risk.md",), ("release", "risk")),
            TeamMemberTemplate("Notes Writer", "Write concise release notes.", "worker", "Own release notes draft.", ("write_file",), ("docs/release-notes.md",), ("release", "notes")),
        ),
    ),
    AgentTeamTemplate(
        "content-ops",
        "Content Ops Team",
        "content",
        "Plan, draft, review, schedule, and track content performance.",
        (
            TeamMemberTemplate("Content Strategist", "Plan channels, topics, and cadence.", "planner", "Own content calendar.", ("scheduler",), ("content/calendar.md",), ("content", "calendar")),
            TeamMemberTemplate("Draft Writer", "Draft posts, scripts, and email copy.", "worker", "Own local content drafts.", ("write_file",), ("content/drafts/",), ("content", "drafts")),
            TeamMemberTemplate("Approval Reviewer", "Check claims, tone, and approval gates before publishing.", "verifier", "Own approval checklist.", ("read_file",), ("content/approval.md",), ("approval", "public-posting")),
        ),
    ),
)


def list_templates() -> list[AgentTeamTemplate]:
    return list(TEMPLATES)


def get_template(template_id: str) -> AgentTeamTemplate | None:
    clean = str(template_id or "").strip().lower()
    return next((template for template in TEMPLATES if template.template_id == clean), None)


def apply_template(cwd: str | Path, template_id: str, *, title: str = "", mission_id: str = "") -> multi_agent_threads.MultiAgentThread:
    template = get_template(template_id)
    if template is None:
        raise KeyError(f"unknown team template: {template_id}")
    root = Path(cwd).expanduser().resolve()
    profiles = [_ensure_profile(root, member) for member in template.members]
    assignments = []
    for member, profile in zip(template.members, profiles):
        assignments.append(
            {
                "agent_id": profile.id,
                "agent_name": profile.name,
                "responsibility": member.responsibility,
                "write_scope": list(member.write_scope),
            }
        )
    return multi_agent_threads.create_thread(
        root,
        title or template.label,
        assignments,
        mission_id=mission_id,
    )


def snapshot() -> dict[str, Any]:
    return {
        "total": len(TEMPLATES),
        "templates": [template.to_dict() for template in TEMPLATES],
    }


def prompt_section() -> str:
    lines = ["# Agent Team Templates"]
    for template in TEMPLATES:
        members = ", ".join(member.name for member in template.members)
        lines.append(f"- {template.template_id}: {template.summary} Members: {members}.")
    return "\n".join(lines)


def _ensure_profile(cwd: Path, member: TeamMemberTemplate) -> agent_profiles.AgentProfile:
    existing = next((profile for profile in agent_profiles.list_profiles(cwd) if profile.name.lower() == member.name.lower()), None)
    if existing:
        return existing
    provider = settings.provider_default({})
    return agent_profiles.create_profile(
        cwd,
        name=member.name,
        purpose=member.purpose,
        agent_type=member.agent_type,
        provider=provider,
        model=settings.model_default(provider, {}),
        tools=list(member.tools),
        memory_scope="workspace",
        routing_hints=list(member.routing_hints),
    )
