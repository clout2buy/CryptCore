"""Shared live-event contract for the desktop daemon and WebUI.

The UI is allowed to stay simple only if runtime events are predictable. This
module keeps the contract small: every event has a name, timestamp, version, and
the required fields for the WebUI to render it without guessing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable


EVENT_VERSION = 1


@dataclass(frozen=True)
class EventSpec:
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()
    terminal: bool = False

    def fields(self) -> frozenset[str]:
        return self.required | self.optional


LIVE_EVENT_SPECS: dict[str, EventSpec] = {
    "ready": EventSpec(optional=frozenset({"snapshot"})),
    "snapshot": EventSpec(required=frozenset({"snapshot"}), optional=frozenset({"id"})),
    "taskStarted": EventSpec(
        optional=frozenset({"id", "taskId", "prompt", "routeRole", "sessionKey", "snapshot", "status"})
    ),
    "taskProgress": EventSpec(required=frozenset({"id", "phase"}), optional=frozenset({"routeRole", "sessionKey", "text"})),
    "intentRouted": EventSpec(
        required=frozenset({"id", "intent", "confidence", "rationale"}),
        optional=frozenset({"routeRole", "sessionKey", "durable", "needsApproval", "needsClarification", "text"}),
    ),
    "thinkingDelta": EventSpec(required=frozenset({"text"}), optional=frozenset({"id", "routeRole", "sessionKey"})),
    "assistantDelta": EventSpec(required=frozenset({"text"}), optional=frozenset({"id", "routeRole", "sessionKey"})),
    "taskFinished": EventSpec(
        required=frozenset({"id", "text"}),
        optional=frozenset({"routeRole", "sessionKey", "currentTokens", "sessionTokens", "snapshot"}),
        terminal=True,
    ),
    "taskFailed": EventSpec(
        required=frozenset({"id", "error"}),
        optional=frozenset({"routeRole", "sessionKey", "snapshot"}),
        terminal=True,
    ),
    "taskEnded": EventSpec(required=frozenset({"taskId", "status"}), terminal=True),
    "toolProgress": EventSpec(
        required=frozenset({"tool", "callId"}),
        optional=frozenset({"id", "routeRole", "sessionKey", "argumentChars", "text"}),
    ),
    "toolCall": EventSpec(
        required=frozenset({"tool", "callId"}),
        optional=frozenset({"id", "routeRole", "sessionKey", "args", "text"}),
    ),
    "toolStarted": EventSpec(
        required=frozenset({"tool", "callId"}),
        optional=frozenset({"id", "routeRole", "sessionKey", "args", "text"}),
    ),
    "toolResult": EventSpec(
        required=frozenset({"tool", "callId", "ok"}),
        optional=frozenset({"id", "routeRole", "sessionKey", "args", "text"}),
    ),
    "approvalRequested": EventSpec(
        required=frozenset({"id", "approvalId", "question", "tool"}),
        optional=frozenset({"sessionKey", "args", "danger", "reason", "text"}),
    ),
    "approvalResolved": EventSpec(
        required=frozenset({"id", "approvalId", "approved"}),
        optional=frozenset({"sessionKey", "text"}),
        terminal=True,
    ),
    "commandResult": EventSpec(required=frozenset({"id", "command", "text"}), optional=frozenset({"skills"})),
    "sessionReset": EventSpec(required=frozenset({"id", "sessionKey"}), optional=frozenset({"text"})),
    "error": EventSpec(required=frozenset({"error"}), optional=frozenset({"id"}), terminal=True),
    "autonomyQuiet": EventSpec(required=frozenset({"cycleId", "text"})),
    "autonomyError": EventSpec(required=frozenset({"error"}), terminal=True),
    "memoryLearned": EventSpec(
        required=frozenset({"text"}),
        optional=frozenset({"lessonId", "tags", "soulChanged"}),
    ),
    "memoryError": EventSpec(required=frozenset({"error"}), terminal=True),
    "memoryJournalUpdated": EventSpec(
        required=frozenset({"text"}),
        optional=frozenset({"category", "promoted", "path"}),
    ),
    "memoryJournalError": EventSpec(required=frozenset({"error"}), terminal=True),
    "missionCreated": EventSpec(required=frozenset({"text"}), optional=frozenset({"goal", "reason"})),
    "missionMatched": EventSpec(required=frozenset({"text"}), optional=frozenset({"goal", "reason"})),
    "missionError": EventSpec(required=frozenset({"error"}), terminal=True),
    "workThreadUpdated": EventSpec(
        required=frozenset({"text"}),
        optional=frozenset({"thread", "state", "nextAction"}),
    ),
    "workThreadError": EventSpec(required=frozenset({"error"}), terminal=True),
    "browserActivity": EventSpec(required=frozenset({"text"}), optional=frozenset({"id", "sessionKey", "status", "url"})),
    "desktopActivity": EventSpec(required=frozenset({"text"}), optional=frozenset({"id", "sessionKey", "status", "action"})),
    "missionStep": EventSpec(required=frozenset({"text"}), optional=frozenset({"id", "sessionKey", "status", "missionId"})),
}


class LiveEventError(ValueError):
    """Raised when a known live event violates the contract."""


def known_event_names() -> tuple[str, ...]:
    return tuple(sorted(LIVE_EVENT_SPECS))


def event_spec(event_name: str) -> EventSpec | None:
    return LIVE_EVENT_SPECS.get(str(event_name or ""))


def is_terminal(event: str | dict) -> bool:
    name = str(event.get("event") if isinstance(event, dict) else event)
    spec = event_spec(name)
    return bool(spec and spec.terminal)


def normalize_event(payload: dict, *, now: float | None = None, strict: bool = True) -> dict:
    if not isinstance(payload, dict):
        raise LiveEventError("live event payload must be a dict")
    event_name = str(payload.get("event") or "").strip()
    if not event_name:
        raise LiveEventError("live event is missing event name")

    event = dict(payload)
    event["event"] = event_name
    event.setdefault("ts", time.time() if now is None else now)
    event.setdefault("eventVersion", EVENT_VERSION)

    spec = event_spec(event_name)
    if spec is None:
        if strict:
            raise LiveEventError(f"unknown live event: {event_name}")
        return event

    missing = [field for field in sorted(spec.required) if field not in event]
    if missing:
        raise LiveEventError(f"{event_name} missing required field(s): {', '.join(missing)}")
    return event


def contract_summary(names: Iterable[str] | None = None) -> list[dict]:
    selected = list(names) if names is not None else known_event_names()
    rows: list[dict] = []
    for name in selected:
        spec = LIVE_EVENT_SPECS[name]
        rows.append(
            {
                "event": name,
                "required": sorted(spec.required),
                "optional": sorted(spec.optional),
                "terminal": spec.terminal,
                "version": EVENT_VERSION,
            }
        )
    return rows
