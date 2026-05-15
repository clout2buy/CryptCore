"""Local revenue, expense, funnel, and analytics ledger."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import session, settings


SCHEMA_VERSION = 1
EVENT_TYPES = {"revenue", "expense", "visit", "lead", "conversion"}


@dataclass(frozen=True)
class MetricEvent:
    event_id: str
    kind: str
    amount: float = 0.0
    currency: str = "USD"
    channel: str = ""
    note: str = ""
    created_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RevenueSummary:
    revenue: float
    expenses: float
    profit: float
    visits: int
    leads: int
    conversions: int
    conversion_rate: float
    revenue_delta: float
    profit_delta: float
    top_channels: list[dict[str, Any]] = field(default_factory=list)


def ledger_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "revenue" / "ledger.json"


def record_event(
    cwd: str | Path,
    kind: str,
    *,
    amount: float = 0.0,
    currency: str = "USD",
    channel: str = "",
    note: str = "",
    created_at: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> MetricEvent:
    clean_kind = str(kind or "").strip().lower()
    if clean_kind not in EVENT_TYPES:
        raise ValueError(f"unknown metric event type: {kind}")
    event = MetricEvent(
        event_id="metric_" + uuid.uuid4().hex[:10],
        kind=clean_kind,
        amount=round(float(amount or 0.0), 2),
        currency=str(currency or "USD").upper()[:8],
        channel=_clean(channel, 80),
        note=_clean(note, 500),
        created_at=int(created_at or time.time()),
        metadata=metadata or {},
    )
    events = list_events(cwd, include_all=True)
    events.append(event)
    _write(cwd, events)
    return event


def list_events(cwd: str | Path, *, include_all: bool = False, limit: int = 500) -> list[MetricEvent]:
    events = _read(cwd)
    if not include_all:
        cutoff = int(time.time()) - 90 * 24 * 60 * 60
        events = [event for event in events if event.created_at >= cutoff]
    events.sort(key=lambda event: event.created_at, reverse=True)
    return events[: max(1, limit)]


def summarize(cwd: str | Path, *, days: int = 7, now: int | None = None) -> RevenueSummary:
    current_now = int(now or time.time())
    window = max(1, int(days)) * 24 * 60 * 60
    current = [event for event in list_events(cwd, include_all=True) if current_now - window <= event.created_at <= current_now]
    previous = [event for event in list_events(cwd, include_all=True) if current_now - (2 * window) <= event.created_at < current_now - window]
    current_totals = _totals(current)
    previous_totals = _totals(previous)
    revenue_total = current_totals["revenue"]
    expenses = current_totals["expense"]
    profit = revenue_total - expenses
    previous_profit = previous_totals["revenue"] - previous_totals["expense"]
    visits = int(current_totals["visit"])
    conversions = int(current_totals["conversion"])
    return RevenueSummary(
        revenue=round(revenue_total, 2),
        expenses=round(expenses, 2),
        profit=round(profit, 2),
        visits=visits,
        leads=int(current_totals["lead"]),
        conversions=conversions,
        conversion_rate=round((conversions / visits) if visits else 0.0, 4),
        revenue_delta=round(revenue_total - previous_totals["revenue"], 2),
        profit_delta=round(profit - previous_profit, 2),
        top_channels=_top_channels(current),
    )


def dashboard_snapshot(cwd: str | Path, *, days: int = 7) -> dict[str, Any]:
    summary = summarize(cwd, days=days)
    return {
        "summary": asdict(summary),
        "events": [asdict(event) for event in list_events(cwd, limit=20)],
        "days": days,
    }


def prompt_section(cwd: str | Path) -> str:
    summary = summarize(cwd)
    if not any((summary.revenue, summary.expenses, summary.visits, summary.leads, summary.conversions)):
        return ""
    return (
        "# Revenue And Metrics\n"
        f"- 7d revenue: {summary.revenue:.2f}; expenses: {summary.expenses:.2f}; profit: {summary.profit:.2f}.\n"
        f"- Funnel: visits={summary.visits}, leads={summary.leads}, conversions={summary.conversions}, conversion_rate={summary.conversion_rate:.2%}.\n"
        f"- Trend: revenue_delta={summary.revenue_delta:.2f}, profit_delta={summary.profit_delta:.2f}."
    )


def _read(cwd: str | Path) -> list[MetricEvent]:
    path = ledger_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[MetricEvent] = []
    for item in data.get("events", []):
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                MetricEvent(
                    event_id=str(item.get("event_id") or ""),
                    kind=str(item.get("kind") or ""),
                    amount=float(item.get("amount") or 0.0),
                    currency=str(item.get("currency") or "USD"),
                    channel=str(item.get("channel") or ""),
                    note=str(item.get("note") or ""),
                    created_at=int(item.get("created_at") or 0),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                )
            )
        except Exception:
            continue
    return [event for event in out if event.event_id and event.kind in EVENT_TYPES]


def _write(cwd: str | Path, events: list[MetricEvent]) -> None:
    path = ledger_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "events": [asdict(event) for event in events]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _totals(events: list[MetricEvent]) -> dict[str, float]:
    totals = {kind: 0.0 for kind in EVENT_TYPES}
    for event in events:
        if event.kind in {"visit", "lead", "conversion"}:
            totals[event.kind] += event.amount or 1
        else:
            totals[event.kind] += event.amount
    return totals


def _top_channels(events: list[MetricEvent]) -> list[dict[str, Any]]:
    channels: dict[str, dict[str, float]] = {}
    for event in events:
        channel = event.channel or "uncategorized"
        row = channels.setdefault(channel, {"revenue": 0.0, "expenses": 0.0, "leads": 0.0, "conversions": 0.0})
        if event.kind == "revenue":
            row["revenue"] += event.amount
        elif event.kind == "expense":
            row["expenses"] += event.amount
        elif event.kind == "lead":
            row["leads"] += event.amount or 1
        elif event.kind == "conversion":
            row["conversions"] += event.amount or 1
    rows = [
        {"channel": channel, **{key: round(value, 2) for key, value in values.items()}}
        for channel, values in channels.items()
    ]
    rows.sort(key=lambda row: (row["revenue"], row["conversions"], row["leads"]), reverse=True)
    return rows[:8]


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
