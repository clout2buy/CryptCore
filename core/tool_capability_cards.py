"""Runtime tool cards with risk, permissions, examples, and usage state."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tools import REGISTRY

from . import evidence, tool_policy


@dataclass(frozen=True)
class ToolUsage:
    total: int = 0
    successes: int = 0
    failures: int = 0
    last_used_at: float = 0.0
    last_summary: str = ""
    state: str = "idle"

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "successes": self.successes,
            "failures": self.failures,
            "lastUsedAt": self.last_used_at,
            "lastSummary": self.last_summary,
            "state": self.state,
        }


@dataclass(frozen=True)
class ToolCapabilityCard:
    name: str
    description: str
    scope: str
    risk: str
    permission_needs: list[str] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)
    recovery_hints: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    parallel_safe: bool = False
    subagent_available: bool = False
    usage: ToolUsage = field(default_factory=ToolUsage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "risk": self.risk,
            "permissionNeeds": self.permission_needs,
            "examples": self.examples,
            "recoveryHints": self.recovery_hints,
            "inputs": self.inputs,
            "requiredInputs": self.required_inputs,
            "outputs": self.outputs,
            "parallelSafe": self.parallel_safe,
            "subagentAvailable": self.subagent_available,
            "usage": self.usage.to_dict(),
        }


def build(*, limit: int = 120) -> list[ToolCapabilityCard]:
    usage = _usage_by_tool()
    cards: list[ToolCapabilityCard] = []
    for schema in REGISTRY.schemas()[: max(1, limit)]:
        name = str(schema.get("name") or "")
        meta = schema.get("x_crypt") if isinstance(schema.get("x_crypt"), dict) else {}
        boundary = tool_policy.classify_action(name, {})
        risk = str(meta.get("risk") or boundary.risk or "low")
        cards.append(
            ToolCapabilityCard(
                name=name,
                description=str(schema.get("description") or ""),
                scope=str(meta.get("capability") or "general"),
                risk=risk,
                permission_needs=[str(item) for item in meta.get("permissionNeeds", [])],
                examples=_json_list(meta.get("examples")),
                recovery_hints=[str(item) for item in meta.get("recoveryHints", [])],
                inputs=[str(item) for item in meta.get("inputs", [])],
                required_inputs=[str(item) for item in meta.get("requiredInputs", [])],
                outputs=[str(item) for item in meta.get("outputs", [])],
                parallel_safe=bool(meta.get("parallelSafe")),
                subagent_available=bool(meta.get("subagentAvailable")),
                usage=usage.get(name, ToolUsage()),
            )
        )
    cards.sort(key=lambda item: (_risk_rank(item.risk), -item.usage.total, item.scope, item.name), reverse=True)
    return cards


def snapshot(*, limit: int = 120) -> dict[str, Any]:
    cards = build(limit=limit)
    by_risk: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    used = 0
    for card in cards:
        by_risk[card.risk] = by_risk.get(card.risk, 0) + 1
        by_scope[card.scope] = by_scope.get(card.scope, 0) + 1
        if card.usage.total:
            used += 1
    return {
        "total": len(cards),
        "used": used,
        "risk": by_risk,
        "scope": by_scope,
        "cards": [card.to_dict() for card in cards],
    }


def prompt_section(*, limit: int = 8) -> str:
    data = snapshot(limit=120)
    cards = data["cards"][: max(1, limit)]
    if not cards:
        return ""
    lines = ["# Tool Capability Cards"]
    lines.append(
        f"- {data['total']} tool(s) loaded; {data['used']} used in current audit memory."
    )
    for card in cards:
        usage = card["usage"]
        used = f", used {usage['total']}x" if usage["total"] else ""
        lines.append(
            f"- {card['name']}: {card['scope']} / {card['risk']} risk{used}; "
            f"permission: {'; '.join(card['permissionNeeds'][:1]) or 'runtime policy'}"
        )
    return "\n".join(lines)


def _usage_by_tool() -> dict[str, ToolUsage]:
    rows: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for item in evidence.audit_entries(limit=1000):
        seen.add(item.audit_id.replace("audit_", "ev_", 1))
        _add_usage(
            rows,
            tool=str(item.source or ""),
            ok=_audit_ok(item.details),
            summary=item.summary,
            created_at=item.created_at,
        )
    for item in evidence.entries():
        if item.id in seen:
            continue
        _add_usage(
            rows,
            tool=str(item.source or ""),
            ok=_evidence_ok(item.details),
            summary=item.summary,
            created_at=item.created_at,
        )
    out: dict[str, ToolUsage] = {}
    for name, row in rows.items():
        if not name or REGISTRY.get(name) is None:
            continue
        total = int(row.get("total") or 0)
        failures = int(row.get("failures") or 0)
        last_used_at = float(row.get("last_used_at") or 0.0)
        out[name] = ToolUsage(
            total=total,
            successes=max(0, total - failures),
            failures=failures,
            last_used_at=last_used_at,
            last_summary=str(row.get("last_summary") or ""),
            state="recent" if last_used_at else "idle",
        )
    return out


def _add_usage(rows: dict[str, dict[str, Any]], *, tool: str, ok: bool | None, summary: str, created_at: float) -> None:
    if not tool:
        return
    row = rows.setdefault(tool, {"total": 0, "failures": 0, "last_used_at": 0.0, "last_summary": ""})
    row["total"] = int(row["total"]) + 1
    if ok is False:
        row["failures"] = int(row["failures"]) + 1
    if created_at >= float(row["last_used_at"]):
        row["last_used_at"] = created_at
        row["last_summary"] = str(summary or "")


def _audit_ok(details: dict[str, Any]) -> bool | None:
    if not isinstance(details, dict):
        return None
    if "ok" in details:
        return bool(details["ok"])
    if str(details.get("action") or "") in {tool_policy.WARN, tool_policy.BLOCK}:
        return False
    return None


def _evidence_ok(details: dict[str, Any]) -> bool | None:
    if isinstance(details, dict) and "ok" in details:
        return bool(details["ok"])
    return None


def _json_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _risk_rank(risk: str) -> int:
    return {"low": 0, "approval": 1, "medium": 2, "high": 3}.get(str(risk or "").lower(), 1)
