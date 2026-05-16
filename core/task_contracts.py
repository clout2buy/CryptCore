"""Structured contracts for vague or multi-step user tasks."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import intent_router, mission_router, redact, session, settings, work_threads


SCHEMA_VERSION = 1
MAX_CONTRACTS = 200
ACTION_RE = re.compile(r"\b(build|create|make|fix|launch|start|track|monitor|research|find|post|send|email|write|upgrade|test|review|automate)\b", re.I)
EXTERNAL_RE = re.compile(r"\b(post|publish|email|dm|reddit|tweet|buy|purchase|pay|stripe|account|login|credential|api key|token|send money)\b", re.I)


@dataclass(frozen=True)
class TaskContract:
    contract_id: str
    cwd: str
    title: str
    outcome: str
    intent: str = "general_task"
    mission_id: str = ""
    thread_id: str = ""
    status: str = "active"
    constraints: list[str] = field(default_factory=list)
    acceptance_checks: list[str] = field(default_factory=list)
    external_gates: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    source_prompt: str = ""
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def contracts_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "contracts" / "task_contracts.json"


def ensure_for_prompt(
    cwd: str | Path,
    text: str,
    *,
    route: intent_router.IntentRoute | None = None,
    mission: mission_router.MissionDecision | None = None,
    thread: work_threads.WorkThread | None = None,
) -> TaskContract | None:
    clean = _clean(text, 1_500)
    if not _should_contract(clean, route):
        return None
    root = Path(cwd).expanduser().resolve()
    now = _now()
    contract_id = "contract_" + _fingerprint(clean)
    existing = next((row for row in list_contracts(root, include_all=True) if row.contract_id == contract_id), None)
    mission_id = mission.goal.goal_id if mission and mission.goal else ""
    thread_id = thread.thread_id if thread else ""
    intent = route.intent if route else "general_task"
    title = _title(clean, mission)
    contract = TaskContract(
        contract_id=contract_id,
        cwd=str(root),
        title=title,
        outcome=_outcome(clean, mission),
        intent=intent,
        mission_id=mission_id or (existing.mission_id if existing else ""),
        thread_id=thread_id or (existing.thread_id if existing else ""),
        constraints=_dedupe([*_constraints(clean, intent), *(existing.constraints if existing else [])]),
        acceptance_checks=_dedupe(_acceptance_checks(clean, intent)),
        external_gates=_dedupe(_external_gates(clean, route)),
        stop_conditions=_dedupe(_stop_conditions(clean, route)),
        source_prompt=clean,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    if existing and contract == replace(existing, updated_at=contract.updated_at):
        return existing
    rows = [row for row in list_contracts(root, include_all=True) if row.contract_id != contract.contract_id]
    rows.insert(0, contract)
    _write(root, rows[:MAX_CONTRACTS])
    return contract


def list_contracts(cwd: str | Path, *, include_all: bool = False, limit: int = 80) -> list[TaskContract]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status == "active"]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_contracts(cwd, include_all=True, limit=80)
    active = [row for row in rows if row.status == "active"]
    return {
        "schema": SCHEMA_VERSION,
        "total": len(rows),
        "active": len(active),
        "approvalGated": sum(1 for row in active if row.external_gates),
        "byIntent": _counts(row.intent for row in rows),
        "contracts": [row.to_dict() for row in rows[:20]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_contracts(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Structured Task Contracts"]
    for row in rows:
        checks = "; ".join(row.acceptance_checks[:3])
        gates = f"; gates={', '.join(row.external_gates[:2])}" if row.external_gates else ""
        lines.append(f"- {row.title}: outcome={row.outcome}; checks={checks}{gates}")
    lines.append("- Use the contract to execute without making the user choreograph planner/builder/reviewer steps.")
    return "\n".join(lines)


def _read(cwd: str | Path) -> list[TaskContract]:
    path = contracts_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("contracts", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                TaskContract(
                    contract_id=str(item.get("contract_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    title=str(item.get("title") or ""),
                    outcome=str(item.get("outcome") or ""),
                    intent=str(item.get("intent") or "general_task"),
                    mission_id=str(item.get("mission_id") or ""),
                    thread_id=str(item.get("thread_id") or ""),
                    status=str(item.get("status") or "active"),
                    constraints=[str(value) for value in item.get("constraints", []) if str(value).strip()],
                    acceptance_checks=[str(value) for value in item.get("acceptance_checks", []) if str(value).strip()],
                    external_gates=[str(value) for value in item.get("external_gates", []) if str(value).strip()],
                    stop_conditions=[str(value) for value in item.get("stop_conditions", []) if str(value).strip()],
                    source_prompt=str(item.get("source_prompt") or ""),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.contract_id and row.cwd]


def _write(cwd: str | Path, rows: list[TaskContract]) -> None:
    path = contracts_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "contracts": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _should_contract(text: str, route: intent_router.IntentRoute | None) -> bool:
    if not text:
        return False
    if route and route.intent in {"conversation", "empty"}:
        return False
    if route and (route.durable or route.intent not in {"conversation", "empty"}):
        return True
    return len(re.findall(r"[a-z0-9']+", text.lower())) >= 8 and bool(ACTION_RE.search(text))


def _title(text: str, mission: mission_router.MissionDecision | None) -> str:
    if mission and mission.goal:
        return mission.goal.title
    sentence = re.split(r"[.!?\n]", text, maxsplit=1)[0].strip(" ,:-")
    return _clean(sentence[:1].upper() + sentence[1:] if sentence else "Task contract", 90)


def _outcome(text: str, mission: mission_router.MissionDecision | None) -> str:
    if mission and mission.goal and mission.goal.success_metric:
        return mission.goal.success_metric
    lower = text.lower()
    if "business" in lower or "revenue" in lower:
        return "Business outcome is planned, assets are created, revenue path is tracked, and external launch actions are approval-gated."
    if "fix" in lower or "bug" in lower or "test" in lower:
        return "Issue is fixed, focused checks pass, and changed files are summarized."
    if "research" in lower or "find" in lower:
        return "Useful answer is grounded in sources or local evidence with next steps."
    return "The requested outcome is completed or advanced with blockers and next actions made explicit."


def _constraints(text: str, intent: str) -> list[str]:
    constraints = [
        "Do the safe local work without asking the user to orchestrate internal phases.",
        "Preserve unrelated user files and existing workspace changes.",
    ]
    if intent in {"code", "file", "browser", "desktop"}:
        constraints.append("Verify changes with the narrowest useful check before claiming completion.")
    if EXTERNAL_RE.search(text):
        constraints.append("Draft external effects locally first.")
    return constraints


def _acceptance_checks(text: str, intent: str) -> list[str]:
    if intent == "code":
        return ["Relevant tests or syntax checks pass.", "Changed files are scoped to the request.", "Residual risks are named."]
    if intent == "business":
        return ["Offer, audience, asset, revenue path, and next action are explicit.", "External launch steps remain approval-gated.", "Tracking surface is updated."]
    if intent == "external_action":
        return ["Draft content/action is prepared locally.", "Exact external effect is shown to the user.", "Explicit approval is received before sending or posting."]
    if intent == "research":
        return ["Answer includes source or local evidence.", "Uncertainty is called out.", "Next useful action is identified."]
    if intent in {"browser", "desktop"}:
        return ["Visible action is narrated.", "Screenshots or observations are logged.", "Sensitive actions stop for approval."]
    return ["A concrete next step is completed.", "Blockers are listed.", "Follow-up state is saved if the task continues."]


def _external_gates(text: str, route: intent_router.IntentRoute | None) -> list[str]:
    if not EXTERNAL_RE.search(text) and not (route and route.needs_approval):
        return []
    return [
        "Approval before posting, sending, buying, paying, creating accounts, or changing external systems.",
        "Credentials and raw secrets are never stored in the contract.",
    ]


def _stop_conditions(text: str, route: intent_router.IntentRoute | None) -> list[str]:
    stops = ["Stop if the user says stop, pause, cancel, or changes the goal."]
    if route and route.needs_approval or EXTERNAL_RE.search(text):
        stops.append("Stop at the approval gate before the external effect.")
    stops.append("Stop and report if required credentials, paid services, or destructive actions are needed.")
    return stops


def _fingerprint(text: str) -> str:
    return hashlib.sha256(_clean(text.lower(), 1_500).encode("utf-8", errors="replace")).hexdigest()[:14]


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        clean = _clean(value, 260)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _clean(value: str, limit: int) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
