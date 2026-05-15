"""Revenue operations dashboard and recommendations."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import revenue, session, settings


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RevenueTarget:
    target_id: str
    cwd: str
    title: str
    target_revenue: float = 0.0
    target_profit: float = 0.0
    due_at: int = 0
    cadence: str = "weekly"
    status: str = "active"
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ops_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "revenue" / "ops.json"


def set_target(
    cwd: str | Path,
    title: str,
    *,
    target_revenue: float = 0.0,
    target_profit: float = 0.0,
    due_at: int = 0,
    cadence: str = "weekly",
) -> RevenueTarget:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    clean_title = _clean(title, 140) or "Revenue target"
    target = RevenueTarget(
        target_id="rev_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        title=clean_title,
        target_revenue=round(float(target_revenue or 0.0), 2),
        target_profit=round(float(target_profit or 0.0), 2),
        due_at=int(due_at or 0),
        cadence=_clean(cadence, 40) or "weekly",
        created_at=now,
        updated_at=now,
    )
    targets = list_targets(root, include_all=True)
    targets.insert(0, target)
    _write(root, targets)
    return target


def list_targets(cwd: str | Path, *, include_all: bool = False, limit: int = 50) -> list[RevenueTarget]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status == "active"]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def dashboard(cwd: str | Path, *, days: int = 30) -> dict[str, Any]:
    summary = revenue.summarize(cwd, days=days)
    targets = list_targets(cwd, include_all=True)
    forecast = _forecast(summary, days)
    return {
        "days": days,
        "summary": asdict(summary),
        "forecast": forecast,
        "targets": [_target_progress(target, summary) for target in targets[:12]],
        "channels": _channels(summary),
        "nextActions": _next_actions(summary, forecast, targets),
    }


def prompt_section(cwd: str | Path) -> str:
    data = dashboard(cwd)
    summary = data["summary"]
    actions = data["nextActions"]
    if not any((summary.get("revenue"), summary.get("expenses"), summary.get("visits"), summary.get("leads"), data["targets"])):
        return ""
    lines = [
        "# Revenue Operations",
        f"- Revenue={summary.get('revenue', 0):.2f}; profit={summary.get('profit', 0):.2f}; leads={summary.get('leads', 0)}; conversion_rate={summary.get('conversion_rate', 0):.2%}.",
        f"- 30d forecast revenue={data['forecast']['revenue30d']:.2f}; profit={data['forecast']['profit30d']:.2f}.",
    ]
    for action in actions[:4]:
        lines.append(f"- Next: {action}")
    return "\n".join(lines)


def _forecast(summary: revenue.RevenueSummary, days: int) -> dict[str, float]:
    window = max(1, int(days))
    revenue_per_day = summary.revenue / window
    profit_per_day = summary.profit / window
    lead_per_day = summary.leads / window
    return {
        "revenue30d": round(revenue_per_day * 30, 2),
        "profit30d": round(profit_per_day * 30, 2),
        "leads30d": round(lead_per_day * 30, 2),
    }


def _target_progress(target: RevenueTarget, summary: revenue.RevenueSummary) -> dict[str, Any]:
    revenue_progress = (summary.revenue / target.target_revenue) if target.target_revenue else 0.0
    profit_progress = (summary.profit / target.target_profit) if target.target_profit else 0.0
    return {
        **target.to_dict(),
        "revenueProgress": round(min(1.0, revenue_progress), 4),
        "profitProgress": round(min(1.0, profit_progress), 4),
        "gapRevenue": round(max(0.0, target.target_revenue - summary.revenue), 2),
        "gapProfit": round(max(0.0, target.target_profit - summary.profit), 2),
    }


def _channels(summary: revenue.RevenueSummary) -> list[dict[str, Any]]:
    rows = []
    for channel in summary.top_channels:
        leads = float(channel.get("leads") or 0)
        conversions = float(channel.get("conversions") or 0)
        rows.append(
            {
                **channel,
                "conversionRate": round((conversions / leads) if leads else 0.0, 4),
                "profit": round(float(channel.get("revenue") or 0) - float(channel.get("expenses") or 0), 2),
            }
        )
    return rows


def _next_actions(summary: revenue.RevenueSummary, forecast: dict[str, float], targets: list[RevenueTarget]) -> list[str]:
    actions: list[str] = []
    if summary.visits == 0:
        actions.append("Pick one acquisition channel and log visits before optimizing anything else.")
    if summary.visits and summary.leads == 0:
        actions.append("Add a lead capture path; traffic exists but no leads are recorded.")
    if summary.leads and summary.conversions == 0:
        actions.append("Follow up with leads and log conversion attempts.")
    if summary.expenses > summary.revenue:
        actions.append("Pause or review spend until the channel shows profit.")
    if targets:
        active = targets[0]
        if active.target_revenue and summary.revenue < active.target_revenue:
            actions.append(f"Close {active.target_revenue - summary.revenue:.2f} more revenue toward {active.title}.")
        if active.target_profit and summary.profit < active.target_profit:
            actions.append(f"Improve margin by {active.target_profit - summary.profit:.2f} toward {active.title}.")
    if forecast.get("leads30d", 0) < 10 and (summary.visits or summary.revenue):
        actions.append("Increase lead flow; current 30d lead forecast is weak.")
    return actions or ["Keep tracking revenue, expenses, visits, leads, and conversions each review cycle."]


def _read(cwd: str | Path) -> list[RevenueTarget]:
    path = ops_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("targets", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                RevenueTarget(
                    target_id=str(item.get("target_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    title=_clean(str(item.get("title") or ""), 140),
                    target_revenue=float(item.get("target_revenue") or 0.0),
                    target_profit=float(item.get("target_profit") or 0.0),
                    due_at=int(item.get("due_at") or 0),
                    cadence=str(item.get("cadence") or "weekly"),
                    status=str(item.get("status") or "active"),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.target_id and row.cwd]


def _write(cwd: str | Path, targets: list[RevenueTarget]) -> None:
    path = ops_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "targets": [target.to_dict() for target in targets]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
