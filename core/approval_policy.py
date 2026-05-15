"""Configurable approval policy rules for autonomous work."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import intent_router, session, settings, tool_policy


SCHEMA_VERSION = 1
ACTIONS = {"allow", "draft", "ask", "block"}
RISKS = {"low", "medium", "high", "critical"}


@dataclass(frozen=True)
class ApprovalRule:
    rule_id: str
    title: str
    action: str
    match: str
    intents: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    risk: str = "medium"
    reason: str = ""
    enabled: bool = True
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalDecision:
    action: str
    risk: str
    rule_id: str = ""
    reason: str = ""
    approval_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def policy_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "approval_policy" / "rules.json"


def ensure_defaults(cwd: str | Path) -> list[ApprovalRule]:
    rows = list_rules(cwd, include_disabled=True)
    if rows:
        return rows
    rows = default_rules()
    _write(cwd, rows)
    return rows


def default_rules() -> list[ApprovalRule]:
    now = _now()
    specs = [
        ("External sends", "ask", "send|post|publish|email|dm|reddit|tweet", ["external_action"], [], "critical", "Anything leaving the machine needs approval."),
        ("Spending and payments", "ask", "buy|purchase|pay|stripe|checkout|credit card", ["business"], [], "critical", "Money movement is approval-gated."),
        ("Account and credential use", "ask", "login|account|credential|password|token|api key", ["browser", "desktop"], [], "high", "Credential use needs explicit approval."),
        ("Local build work", "allow", "edit|build|test|fix|refactor", ["code", "file"], ["read_file", "edit_file", "write_file"], "medium", "Local workspace work is allowed with verification."),
        ("Destructive operations", "block", "reset --hard|rm -rf|remove-item|format|drop table", ["code"], ["bash", "bash_start"], "critical", "Destructive operations are blocked unless policy is changed deliberately."),
    ]
    return [
        ApprovalRule(
            rule_id="policy_" + uuid.uuid4().hex[:10],
            title=title,
            action=action,
            match=match,
            intents=intents,
            tools=tools,
            risk=risk,
            reason=reason,
            created_at=now,
            updated_at=now,
        )
        for title, action, match, intents, tools, risk, reason in specs
    ]


def upsert_rule(
    cwd: str | Path,
    *,
    title: str,
    action: str,
    match: str,
    intents: list[str] | None = None,
    tools: list[str] | None = None,
    risk: str = "medium",
    reason: str = "",
) -> ApprovalRule:
    clean_title = _clean(title, 140) or "Approval rule"
    rows = list_rules(cwd, include_disabled=True)
    existing = next((row for row in rows if row.title.lower() == clean_title.lower()), None)
    now = _now()
    rule = ApprovalRule(
        rule_id=existing.rule_id if existing else "policy_" + uuid.uuid4().hex[:10],
        title=clean_title,
        action=_action(action),
        match=_clean(match, 300),
        intents=_dedupe(intents or []),
        tools=_dedupe(tools or []),
        risk=_risk(risk),
        reason=_clean(reason, 500),
        enabled=True,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    rows = [row for row in rows if row.rule_id != rule.rule_id]
    rows.insert(0, rule)
    _write(cwd, rows)
    return rule


def decide(cwd: str | Path, text: str = "", *, tool_name: str = "", intent: str = "") -> ApprovalDecision:
    rows = [row for row in ensure_defaults(cwd) if row.enabled]
    route = intent or (intent_router.route(text).intent if text else "")
    boundary = tool_policy.classify_action(tool_name, {"text": text}) if tool_name else None
    for rule in rows:
        if rule.intents and route and route not in rule.intents:
            continue
        if rule.tools and tool_name and tool_name not in rule.tools:
            continue
        if rule.match and not re.search(rule.match, f"{text} {tool_name}", flags=re.I):
            continue
        return ApprovalDecision(
            action=rule.action,
            risk=rule.risk,
            rule_id=rule.rule_id,
            reason=rule.reason or rule.title,
            approval_required=rule.action in {"ask", "draft"},
        )
    if boundary and boundary.requires_approval:
        return ApprovalDecision("ask", boundary.risk, reason=boundary.reason, approval_required=True)
    return ApprovalDecision("allow", "low", reason="no approval rule matched", approval_required=False)


def list_rules(cwd: str | Path, *, include_disabled: bool = False, limit: int = 80) -> list[ApprovalRule]:
    rows = _read(cwd)
    if not include_disabled:
        rows = [row for row in rows if row.enabled]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def set_enabled(cwd: str | Path, rule_id: str, enabled: bool) -> ApprovalRule:
    rows = []
    updated: ApprovalRule | None = None
    for row in list_rules(cwd, include_disabled=True):
        if row.rule_id != rule_id:
            rows.append(row)
            continue
        updated = replace(row, enabled=bool(enabled), updated_at=_now())
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown approval rule: {rule_id}")
    _write(cwd, rows)
    return updated


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = ensure_defaults(cwd)
    enabled = [row for row in rows if row.enabled]
    return {
        "total": len(rows),
        "enabled": len(enabled),
        "ask": sum(1 for row in enabled if row.action == "ask"),
        "draft": sum(1 for row in enabled if row.action == "draft"),
        "block": sum(1 for row in enabled if row.action == "block"),
        "rules": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, text: str = "", *, limit: int = 6) -> str:
    decision = decide(cwd, text)
    rows = list_rules(cwd, limit=limit)
    lines = [
        "# Approval Policy",
        f"- current_decision={decision.action}; risk={decision.risk}; approval_required={decision.approval_required}; reason={decision.reason}",
    ]
    for row in rows[:limit]:
        lines.append(f"- {row.action}/{row.risk}: {row.title}; match={row.match}")
    return "\n".join(lines)


def _read(cwd: str | Path) -> list[ApprovalRule]:
    path = policy_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("rules", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                ApprovalRule(
                    rule_id=str(item.get("rule_id") or ""),
                    title=str(item.get("title") or ""),
                    action=_action(str(item.get("action") or "ask")),
                    match=str(item.get("match") or ""),
                    intents=[str(value) for value in item.get("intents", []) if str(value).strip()],
                    tools=[str(value) for value in item.get("tools", []) if str(value).strip()],
                    risk=_risk(str(item.get("risk") or "medium")),
                    reason=str(item.get("reason") or ""),
                    enabled=bool(item.get("enabled", True)),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.rule_id and row.title]


def _write(cwd: str | Path, rows: list[ApprovalRule]) -> None:
    path = policy_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "rules": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _action(value: str) -> str:
    clean = str(value or "ask").strip().lower()
    return clean if clean in ACTIONS else "ask"


def _risk(value: str) -> str:
    clean = str(value or "medium").strip().lower()
    return clean if clean in RISKS else "medium"


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value, 80)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
