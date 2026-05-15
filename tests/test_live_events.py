from __future__ import annotations

import pytest

from core import live_events


def test_live_event_contract_contains_core_streaming_events():
    names = set(live_events.known_event_names())

    assert {
        "taskStarted",
        "taskProgress",
        "intentRouted",
        "thinkingDelta",
        "assistantDelta",
        "toolProgress",
        "toolCall",
        "toolStarted",
        "toolResult",
        "approvalRequested",
        "approvalResolved",
        "missionCreated",
        "missionMatched",
        "browserActivity",
        "desktopActivity",
        "missionStep",
        "taskFinished",
        "taskFailed",
    } <= names


def test_normalize_event_adds_version_and_timestamp():
    event = live_events.normalize_event(
        {"event": "assistantDelta", "text": "hi"},
        now=123.0,
    )

    assert event["eventVersion"] == live_events.EVENT_VERSION
    assert event["ts"] == 123.0
    assert event["text"] == "hi"


def test_normalize_event_rejects_known_event_missing_required_field():
    with pytest.raises(live_events.LiveEventError, match="assistantDelta missing"):
        live_events.normalize_event({"event": "assistantDelta"})


def test_unknown_events_can_pass_in_compatibility_mode():
    event = live_events.normalize_event({"event": "futureEvent", "text": "ok"}, strict=False, now=5.0)

    assert event["event"] == "futureEvent"
    assert event["eventVersion"] == live_events.EVENT_VERSION
    assert event["ts"] == 5.0


def test_terminal_event_metadata_is_available():
    assert live_events.is_terminal("taskFinished") is True
    assert live_events.is_terminal({"event": "toolProgress"}) is False
