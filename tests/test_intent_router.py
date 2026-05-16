from __future__ import annotations

from core import intent_router


def test_intent_router_keeps_short_chat_as_conversation():
    route = intent_router.route("hey what's up")

    assert route.intent == "conversation"
    assert route.route_role == ""


def test_intent_router_keeps_casual_testing_as_conversation():
    route = intent_router.route("idk testing u lol")

    assert route.intent == "conversation"
    assert route.route_role == ""


def test_intent_router_routes_code_to_builder():
    route = intent_router.route("fix the WebUI flicker bug and add tests")

    assert route.intent == "code"
    assert route.route_role == "builder"
    assert route.confidence >= 0.70


def test_intent_router_flags_external_actions_for_approval():
    route = intent_router.route("post this to reddit when it is ready")

    assert route.intent == "external_action"
    assert route.needs_approval is True
    assert route.durable is True


def test_intent_router_prompt_hint_is_compact():
    route = intent_router.route("start a business and track revenue weekly")
    hint = intent_router.prompt_hint(route)

    assert "intent=business" in hint
    assert "durable mission" in hint
