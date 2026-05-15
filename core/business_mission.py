"""Business mission template for autonomous launch work."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from . import goals, mission_router, work_threads


@dataclass(frozen=True)
class BusinessStage:
    key: str
    title: str
    deliverable: str
    approval_required: bool = False


STAGES = (
    BusinessStage("idea", "Clarify the business idea", "One-sentence business thesis and constraints."),
    BusinessStage("market", "Identify target market and pain", "Audience, problem, alternatives, and urgency."),
    BusinessStage("offer", "Shape the offer", "Offer, price hypothesis, guarantee, and first package."),
    BusinessStage("brand", "Create brand direction", "Name options, voice, visual direction, and trust signals."),
    BusinessStage("landing", "Build landing page or sales asset", "Local launch page, copy, CTA, and proof plan."),
    BusinessStage("payment", "Prepare payment path", "Draft checkout/payment workflow and approval checklist.", True),
    BusinessStage("content", "Prepare content and outreach", "Launch posts, email/DM drafts, and channel plan.", True),
    BusinessStage("operations", "Set up operations tracker", "Leads, customers, blockers, fulfillment, and support notes."),
    BusinessStage("analytics", "Set up analytics and revenue tracking", "Metrics, conversion funnel, revenue, expenses, and review cadence."),
    BusinessStage("launch", "Launch with approval gates", "Final launch checklist with live external actions separated for approval.", True),
)


def is_business_text(text: str) -> bool:
    lower = str(text or "").lower()
    return "business" in lower or any(term in lower for term in ("revenue", "income", "customers", "leads", "sales funnel", "stripe"))


def stage_tasks() -> list[dict]:
    return [
        {
            "title": stage.title,
            "status": "pending",
            "key": stage.key,
            "deliverable": stage.deliverable,
            "approval_required": stage.approval_required,
        }
        for stage in STAGES
    ]


def blockers() -> list[str]:
    return [
        "Live payment setup, spending money, posting publicly, sending outreach, or creating accounts needs explicit approval.",
    ]


def success_metrics() -> list[str]:
    return [
        "Business thesis, audience, offer, brand, landing asset, operations tracker, and analytics plan are created.",
        "Payment and external launch actions are drafted locally and held for approval before going live.",
        "Revenue, expenses, leads, blockers, and next actions stay tracked on a cadence.",
    ]


def create_business_mission(cwd: str | Path, request: str):
    """Create or reuse a business mission and force the full template onto it."""
    decision = mission_router.observe(cwd, request)
    goal = decision.goal
    if goal is None:
        goal = goals.add_goal(
            "Build and operate the business",
            description=request,
            workspace=cwd,
            success_metric="Business launch assets, operations, analytics, and revenue path are staged.",
            cadence="weekly",
            priority=4,
            tags=["auto", "mission", "business", "build", "monitor"],
        )
    thread = work_threads.ensure_for_goal(goal, prompt_text=request, source="business-template")
    thread = work_threads.update_thread(
        thread.thread_id,
        blockers=blockers(),
        tasks=stage_tasks(),
        success_metrics=success_metrics(),
        last_note="business mission template applied",
        source="business-template",
    )
    return goal, thread


def prompt_section() -> str:
    lines = ["# Business Mission Template"]
    for stage in STAGES:
        gate = " approval-gated" if stage.approval_required else ""
        lines.append(f"- {stage.key}: {stage.title}{gate}")
    return "\n".join(lines)


def template_snapshot() -> dict:
    return {"stages": [asdict(stage) for stage in STAGES], "success_metrics": success_metrics(), "blockers": blockers()}
