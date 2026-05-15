"""External integration registry and scope display."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import settings


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IntegrationDefinition:
    integration_id: str
    label: str
    category: str
    scopes: list[str] = field(default_factory=list)
    approval_required: bool = True


@dataclass(frozen=True)
class IntegrationState:
    integration_id: str
    enabled: bool = False
    configured: bool = False
    status: str = "disabled"
    notes: str = ""
    updated_at: int = 0


@dataclass(frozen=True)
class IntegrationCard:
    integration_id: str
    label: str
    category: str
    scopes: list[str]
    enabled: bool
    configured: bool
    status: str
    approval_required: bool
    notes: str = ""


CATALOG = (
    IntegrationDefinition("github", "GitHub", "code", ["repo read", "pull requests", "issues", "actions"]),
    IntegrationDefinition("email", "Email", "communications", ["read inbox", "draft email", "send requires approval"]),
    IntegrationDefinition("calendar", "Calendar", "operations", ["read availability", "draft events", "modify requires approval"]),
    IntegrationDefinition("storage", "Drive / Storage", "files", ["read files", "draft docs", "write requires approval"]),
    IntegrationDefinition("slack", "Slack", "communications", ["read channels", "draft messages", "send requires approval"]),
    IntegrationDefinition("discord", "Discord", "communications", ["read servers", "draft posts", "send requires approval"]),
    IntegrationDefinition("reddit", "Reddit", "social", ["read posts", "draft posts", "post requires approval"]),
    IntegrationDefinition("stripe", "Stripe", "payments", ["read balances", "draft products", "payments require approval"]),
    IntegrationDefinition("analytics", "Analytics", "metrics", ["read dashboards", "summarize funnels"]),
    IntegrationDefinition("database", "Database", "data", ["read configured data", "writes require approval"]),
)


def integrations_path() -> Path:
    return settings.APP_DIR / "integrations.json"


def list_integrations() -> list[IntegrationCard]:
    states = {state.integration_id: state for state in _read_states()}
    cards: list[IntegrationCard] = []
    for definition in CATALOG:
        state = states.get(definition.integration_id) or IntegrationState(integration_id=definition.integration_id)
        cards.append(
            IntegrationCard(
                integration_id=definition.integration_id,
                label=definition.label,
                category=definition.category,
                scopes=list(definition.scopes),
                enabled=bool(state.enabled),
                configured=bool(state.configured),
                status=state.status,
                approval_required=definition.approval_required,
                notes=state.notes,
            )
        )
    return cards


def set_integration(
    integration_id: str,
    *,
    enabled: bool | None = None,
    configured: bool | None = None,
    notes: str = "",
) -> IntegrationState:
    definition = _definition(integration_id)
    if definition is None:
        raise KeyError(f"unknown integration: {integration_id}")
    states = {state.integration_id: state for state in _read_states()}
    existing = states.get(definition.integration_id) or IntegrationState(integration_id=definition.integration_id)
    final_configured = existing.configured if configured is None else bool(configured)
    final_enabled = existing.enabled if enabled is None else bool(enabled)
    if final_enabled and not final_configured:
        status = "needs-setup"
        final_enabled = False
    else:
        status = "enabled" if final_enabled else ("configured" if final_configured else "disabled")
    state = IntegrationState(
        integration_id=definition.integration_id,
        enabled=final_enabled,
        configured=final_configured,
        status=status,
        notes=_clean(notes or existing.notes),
        updated_at=int(time.time()),
    )
    states[definition.integration_id] = state
    _write_states(list(states.values()))
    return state


def scope_summary() -> str:
    lines = ["# External Integrations"]
    for card in list_integrations():
        state = "enabled" if card.enabled else card.status
        lines.append(f"- {card.label}: {state}; scopes: {', '.join(card.scopes)}")
    return "\n".join(lines)


def snapshot() -> list[dict[str, Any]]:
    return [asdict(card) for card in list_integrations()]


def _definition(integration_id: str) -> IntegrationDefinition | None:
    clean = str(integration_id or "").strip().lower()
    return next((item for item in CATALOG if item.integration_id == clean), None)


def _read_states() -> list[IntegrationState]:
    path = integrations_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[IntegrationState] = []
    for item in data.get("integrations", []):
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                IntegrationState(
                    integration_id=str(item.get("integration_id") or ""),
                    enabled=bool(item.get("enabled")),
                    configured=bool(item.get("configured")),
                    status=str(item.get("status") or "disabled"),
                    notes=str(item.get("notes") or ""),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [state for state in out if _definition(state.integration_id)]


def _write_states(states: list[IntegrationState]) -> None:
    path = integrations_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "integrations": [asdict(state) for state in states]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _clean(value: str, limit: int = 500) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
