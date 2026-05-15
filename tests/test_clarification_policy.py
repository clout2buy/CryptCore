from __future__ import annotations

from core import clarification_policy, intent_router


def test_clarification_policy_executes_confident_safe_routes():
    decision = clarification_policy.decide(intent_router.route("fix the WebUI bug and run tests"))

    assert decision.action == "execute"


def test_clarification_policy_gates_external_actions():
    decision = clarification_policy.decide(intent_router.route("post this to reddit"))

    assert decision.action == "approval_gate"
    assert "approval" in decision.reason


def test_clarification_policy_clarifies_low_confidence_routes():
    route = intent_router.IntentRoute(
        intent="general_task",
        route_role="planner",
        confidence=0.42,
        rationale="unclear",
        durable=True,
    )

    decision = clarification_policy.decide(route)

    assert decision.action == "clarify"
    assert decision.question
