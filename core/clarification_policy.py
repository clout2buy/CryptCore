"""Decision policy for acting, clarifying, or approval-gating a routed prompt."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .intent_router import IntentRoute


@dataclass(frozen=True)
class ActionDecision:
    action: str
    reason: str
    question: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def decide(route: IntentRoute) -> ActionDecision:
    if route.needs_approval:
        return ActionDecision(
            "approval_gate",
            "external state-changing actions require explicit approval",
            "I can prepare it, but I need your approval before I post, buy, message, or create an external account.",
        )
    if route.needs_clarification or route.confidence < 0.60:
        return ActionDecision(
            "clarify",
            "route confidence is too low for autonomous execution",
            "What outcome do you want me to optimize for?",
        )
    return ActionDecision("execute", "safe enough to continue autonomously")


def prompt_hint(decision: ActionDecision) -> str:
    if decision.action == "execute":
        return "action_policy=execute; continue with the next safe useful step"
    if decision.action == "approval_gate":
        return (
            "action_policy=approval_gate; prepare drafts, plans, and checks, but ask explicit approval "
            "before external posting, purchases, account creation, credential use, or destructive actions"
        )
    return f"action_policy=clarify; ask one concise question before tool-heavy work: {decision.question}"
