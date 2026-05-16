from __future__ import annotations

from core import live_event_integrity


def test_live_event_integrity_detects_gaps_and_duplicates():
    events = [
        {"event": "taskStarted", "seq": 1, "ts": 100.0},
        {"event": "thinkingDelta", "seq": 2, "ts": 101.0, "text": "thinking"},
        {"event": "assistantDelta", "seq": 4, "ts": 102.0, "text": "hi"},
        {"event": "assistantDelta", "seq": 4, "ts": 103.0, "text": "dupe"},
    ]

    data = live_event_integrity.analyze(events, active_task={"id": "task"}, now=104.0)

    assert data["status"] == "warning"
    assert data["gaps"] == 1
    assert data["duplicates"] == 1
    assert any(issue["kind"] == "missing-seq" for issue in data["issues"])


def test_live_event_integrity_detects_stalled_thinking():
    events = [
        {"event": "taskStarted", "seq": 1, "ts": 100.0},
        {"event": "thinkingDelta", "seq": 2, "ts": 101.0, "text": "thinking"},
    ]

    data = live_event_integrity.analyze(events, active_task={"id": "task"}, now=130.0)

    assert data["status"] == "warning"
    assert any(issue["kind"] == "stale-thinking" for issue in data["issues"])
    assert "Live Event Integrity" in live_event_integrity.prompt_section(events, active_task={"id": "task"})
