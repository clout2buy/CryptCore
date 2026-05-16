"""Integrity checks for WebUI live event streams."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from . import live_events


STALE_STREAM_SECONDS = 20
STALE_THINKING_SECONDS = 12


@dataclass(frozen=True)
class EventIssue:
    kind: str
    severity: str
    detail: str
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EventIntegrity:
    status: str
    total: int
    first_seq: int
    last_seq: int
    gaps: int
    duplicates: int
    unknown: int
    terminal_seen: bool
    newest_age_seconds: int
    issues: list[EventIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def analyze(
    events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    active_task: object = None,
    now: float | None = None,
) -> dict[str, Any]:
    current = time.time() if now is None else float(now)
    rows = [event for event in events if isinstance(event, dict)]
    seqs = [_seq(event) for event in rows if _seq(event) > 0]
    issues: list[EventIssue] = []
    duplicates = _duplicates(seqs)
    for seq in duplicates[:5]:
        issues.append(EventIssue("duplicate-seq", "warning", f"duplicate event seq {seq}", seq))
    gaps = _gaps(seqs)
    for seq in gaps[:5]:
        issues.append(EventIssue("missing-seq", "warning", f"missing event seq {seq}", seq))
    unknown = 0
    for event in rows:
        name = str(event.get("event") or "")
        if live_events.event_spec(name) is None:
            unknown += 1
            issues.append(EventIssue("unknown-event", "info", f"unknown event {name or '<empty>'}", _seq(event)))
            continue
        try:
            live_events.normalize_event(dict(event), strict=True)
        except Exception as exc:
            issues.append(EventIssue("contract", "warning", str(exc), _seq(event)))
    terminal_seen = any(live_events.is_terminal(event) for event in rows)
    newest_ts = max([float(event.get("ts") or 0) for event in rows] or [0.0])
    newest_age = int(max(0, current - newest_ts)) if newest_ts else 0
    if active_task and rows and newest_age > STALE_STREAM_SECONDS and not terminal_seen:
        issues.append(EventIssue("stale-stream", "warning", f"active task but newest event is {newest_age}s old", max(seqs or [0])))
    last_thinking = _last_event(rows, "thinkingDelta")
    if active_task and last_thinking and not terminal_seen:
        age = int(max(0, current - float(last_thinking.get("ts") or current)))
        if age > STALE_THINKING_SECONDS:
            issues.append(EventIssue("stale-thinking", "warning", f"thinking stream stalled for {age}s", _seq(last_thinking)))
    status = "warning" if any(issue.severity == "warning" for issue in issues) else "ok"
    return EventIntegrity(
        status=status,
        total=len(rows),
        first_seq=min(seqs or [0]),
        last_seq=max(seqs or [0]),
        gaps=len(gaps),
        duplicates=len(duplicates),
        unknown=unknown,
        terminal_seen=terminal_seen,
        newest_age_seconds=newest_age,
        issues=issues[:20],
    ).to_dict()


def prompt_section(events: list[dict[str, Any]], *, active_task: object = None) -> str:
    data = analyze(events, active_task=active_task)
    if data["status"] == "ok":
        return ""
    lines = ["# Live Event Integrity"]
    lines.append(f"- status={data['status']} total={data['total']} last_seq={data['last_seq']} gaps={data['gaps']} duplicates={data['duplicates']}")
    for issue in data["issues"][:6]:
        lines.append(f"- {issue['severity']} {issue['kind']}: {issue['detail']}")
    return "\n".join(lines)


def _seq(event: dict[str, Any]) -> int:
    try:
        return int(event.get("seq") or 0)
    except (TypeError, ValueError):
        return 0


def _duplicates(seqs: list[int]) -> list[int]:
    seen: set[int] = set()
    dupes: list[int] = []
    for seq in seqs:
        if seq in seen and seq not in dupes:
            dupes.append(seq)
        seen.add(seq)
    return dupes


def _gaps(seqs: list[int]) -> list[int]:
    if len(seqs) < 2:
        return []
    ordered = sorted(set(seqs))
    missing: list[int] = []
    for left, right in zip(ordered, ordered[1:]):
        if right - left > 1:
            missing.extend(range(left + 1, right))
    return missing


def _last_event(events: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("event") == name:
            return event
    return {}
