"""Mission budget ledger for time, model spend, revenue, and risk."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import model_usage_ledger, revenue_ops, session, settings, work_threads


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MissionBudget:
    mission_id: str
    title: str
    max_cost_usd: float = 5.0
    max_minutes: int = 120
    risk_budget: str = "medium"
    revenue_target_usd: float = 0.0
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MissionSpend:
    mission_id: str
    minutes: int = 0
    model_cost_usd: float = 0.0
    revenue_usd: float = 0.0
    note: str = ""
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ledger_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "mission_budget" / "ledger.json"


def set_budget(
    cwd: str | Path,
    mission_id: str,
    title: str,
    *,
    max_cost_usd: float = 5.0,
    max_minutes: int = 120,
    risk_budget: str = "medium",
    revenue_target_usd: float = 0.0,
) -> MissionBudget:
    now = _now()
    clean_id = _clean(mission_id, 120)
    if not clean_id:
        raise ValueError("mission_id cannot be empty")
    budgets, spends = _read(cwd)
    budget = MissionBudget(
        mission_id=clean_id,
        title=_clean(title, 180) or clean_id,
        max_cost_usd=round(max(0.0, float(max_cost_usd or 0.0)), 4),
        max_minutes=max(0, int(max_minutes or 0)),
        risk_budget=_risk(risk_budget),
        revenue_target_usd=round(max(0.0, float(revenue_target_usd or 0.0)), 2),
        created_at=budgets.get(clean_id, MissionBudget(clean_id, clean_id, created_at=now)).created_at or now,
        updated_at=now,
    )
    budgets[clean_id] = budget
    _write(cwd, budgets.values(), spends)
    return budget


def record_spend(
    cwd: str | Path,
    mission_id: str,
    *,
    minutes: int = 0,
    model_cost_usd: float = 0.0,
    revenue_usd: float = 0.0,
    note: str = "",
) -> MissionSpend:
    clean_id = _clean(mission_id, 120)
    if not clean_id:
        raise ValueError("mission_id cannot be empty")
    budgets, spends = _read(cwd)
    spend = MissionSpend(
        mission_id=clean_id,
        minutes=max(0, int(minutes or 0)),
        model_cost_usd=round(max(0.0, float(model_cost_usd or 0.0)), 6),
        revenue_usd=round(max(0.0, float(revenue_usd or 0.0)), 2),
        note=_clean(note, 300),
        created_at=_now(),
    )
    spends.append(spend)
    _write(cwd, budgets.values(), spends[-500:])
    return spend


def snapshot(cwd: str | Path) -> dict[str, Any]:
    budgets, spends = _read(cwd)
    threads = work_threads.list_threads(cwd, include_all=True)
    usage = model_usage_ledger.snapshot(cwd)
    revenue = revenue_ops.dashboard(cwd)
    cards = [_mission_card(thread, budgets, spends, revenue) for thread in threads[:30]]
    budget_only = [
        _budget_card(budget, spends, revenue)
        for mission_id, budget in budgets.items()
        if mission_id not in {thread.goal_id or thread.thread_id for thread in threads}
    ]
    cards.extend(budget_only)
    total_cost = round(sum(card["modelCostUsd"] for card in cards), 6)
    total_minutes = sum(card["minutes"] for card in cards)
    over = [card for card in cards if card["status"] == "over-budget"]
    return {
        "schema": SCHEMA_VERSION,
        "missions": len(cards),
        "overBudget": len(over),
        "totalMinutes": total_minutes,
        "modelCostUsd": total_cost,
        "workspaceModelCostUsd": usage.get("costEstimatedUsd", 0),
        "workspaceTokensEstimated": usage.get("tokensEstimated", 0),
        "revenue30d": revenue.get("forecast", {}).get("revenue30d", 0),
        "cards": cards[:30],
    }


def prompt_section(cwd: str | Path, *, limit: int = 6) -> str:
    data = snapshot(cwd)
    if not data["cards"]:
        return ""
    lines = [
        "# Mission Budget Ledger",
        f"- missions={data['missions']}; over_budget={data['overBudget']}; minutes={data['totalMinutes']}; model_cost=${data['modelCostUsd']:.6f}; workspace_model_cost=${float(data['workspaceModelCostUsd']):.6f}",
    ]
    for card in data["cards"][:limit]:
        lines.append(
            f"- {card['status']} {card['title']}: minutes={card['minutes']}/{card['maxMinutes']}; "
            f"cost=${card['modelCostUsd']:.6f}/${card['maxCostUsd']:.2f}; risk={card['riskBudget']}; revenue_target=${card['revenueTargetUsd']:.2f}"
        )
    return "\n".join(lines)


def _mission_card(thread: work_threads.WorkThread, budgets: dict[str, MissionBudget], spends: list[MissionSpend], revenue: dict[str, Any]) -> dict[str, Any]:
    mission_id = thread.goal_id or thread.thread_id
    budget = budgets.get(mission_id) or _default_budget(mission_id, thread.title, thread.priority, blocked=bool(thread.blockers))
    spend = _spend_totals(mission_id, spends)
    observed_minutes = max(0, int(((thread.updated_at or thread.created_at) - thread.created_at) / 60)) if thread.created_at else 0
    minutes = spend["minutes"] + observed_minutes
    status = _status(minutes, spend["modelCostUsd"], budget, blocked=bool(thread.blockers))
    return {
        "missionId": mission_id,
        "threadId": thread.thread_id,
        "title": thread.title,
        "state": thread.state,
        "status": status,
        "minutes": minutes,
        "maxMinutes": budget.max_minutes,
        "modelCostUsd": spend["modelCostUsd"],
        "maxCostUsd": budget.max_cost_usd,
        "revenueUsd": spend["revenueUsd"],
        "revenueTargetUsd": budget.revenue_target_usd,
        "riskBudget": budget.risk_budget,
        "nextAction": thread.next_action,
        "blockers": thread.blockers,
        "forecastRevenue30d": revenue.get("forecast", {}).get("revenue30d", 0),
    }


def _budget_card(budget: MissionBudget, spends: list[MissionSpend], revenue: dict[str, Any]) -> dict[str, Any]:
    spend = _spend_totals(budget.mission_id, spends)
    return {
        "missionId": budget.mission_id,
        "threadId": "",
        "title": budget.title,
        "state": "budget-only",
        "status": _status(spend["minutes"], spend["modelCostUsd"], budget, blocked=False),
        "minutes": spend["minutes"],
        "maxMinutes": budget.max_minutes,
        "modelCostUsd": spend["modelCostUsd"],
        "maxCostUsd": budget.max_cost_usd,
        "revenueUsd": spend["revenueUsd"],
        "revenueTargetUsd": budget.revenue_target_usd,
        "riskBudget": budget.risk_budget,
        "nextAction": "Attach this budget to a mission thread.",
        "blockers": [],
        "forecastRevenue30d": revenue.get("forecast", {}).get("revenue30d", 0),
    }


def _default_budget(mission_id: str, title: str, priority: int, *, blocked: bool) -> MissionBudget:
    risk = "high" if blocked else ("high" if priority >= 5 else "medium" if priority >= 3 else "low")
    return MissionBudget(
        mission_id=mission_id,
        title=title,
        max_cost_usd=10.0 if risk == "high" else 5.0 if risk == "medium" else 2.0,
        max_minutes=240 if risk == "high" else 120 if risk == "medium" else 60,
        risk_budget=risk,
    )


def _spend_totals(mission_id: str, spends: list[MissionSpend]) -> dict[str, float | int]:
    rows = [spend for spend in spends if spend.mission_id == mission_id]
    return {
        "minutes": sum(spend.minutes for spend in rows),
        "modelCostUsd": round(sum(spend.model_cost_usd for spend in rows), 6),
        "revenueUsd": round(sum(spend.revenue_usd for spend in rows), 2),
    }


def _status(minutes: int, cost: float, budget: MissionBudget, *, blocked: bool) -> str:
    if budget.max_minutes and minutes > budget.max_minutes:
        return "over-budget"
    if budget.max_cost_usd and cost > budget.max_cost_usd:
        return "over-budget"
    if blocked:
        return "blocked"
    if budget.max_minutes and minutes > budget.max_minutes * 0.8:
        return "watch"
    if budget.max_cost_usd and cost > budget.max_cost_usd * 0.8:
        return "watch"
    return "on-track"


def _read(cwd: str | Path) -> tuple[dict[str, MissionBudget], list[MissionSpend]]:
    path = ledger_path(cwd)
    if not path.exists():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return {}, []
    budgets = {}
    spends = []
    for item in data.get("budgets", []):
        if not isinstance(item, dict):
            continue
        try:
            budget = MissionBudget(
                mission_id=str(item.get("mission_id") or ""),
                title=str(item.get("title") or ""),
                max_cost_usd=float(item.get("max_cost_usd") or 0.0),
                max_minutes=int(item.get("max_minutes") or 0),
                risk_budget=_risk(str(item.get("risk_budget") or "medium")),
                revenue_target_usd=float(item.get("revenue_target_usd") or 0.0),
                created_at=int(item.get("created_at") or 0),
                updated_at=int(item.get("updated_at") or 0),
            )
        except Exception:
            continue
        if budget.mission_id:
            budgets[budget.mission_id] = budget
    for item in data.get("spends", []):
        if not isinstance(item, dict):
            continue
        try:
            spends.append(
                MissionSpend(
                    mission_id=str(item.get("mission_id") or ""),
                    minutes=int(item.get("minutes") or 0),
                    model_cost_usd=float(item.get("model_cost_usd") or 0.0),
                    revenue_usd=float(item.get("revenue_usd") or 0.0),
                    note=str(item.get("note") or ""),
                    created_at=int(item.get("created_at") or 0),
                )
            )
        except Exception:
            continue
    return budgets, [spend for spend in spends if spend.mission_id]


def _write(cwd: str | Path, budgets: Any, spends: list[MissionSpend]) -> None:
    path = ledger_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": SCHEMA_VERSION,
                "budgets": [budget.to_dict() for budget in budgets],
                "spends": [spend.to_dict() for spend in spends],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _risk(value: str) -> str:
    clean = str(value or "medium").strip().lower()
    return clean if clean in {"low", "medium", "high", "critical"} else "medium"


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
