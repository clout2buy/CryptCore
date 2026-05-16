"""Connector readiness and safe-action policy before external work."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import credential_vault, integrations, mcp_gateway


SCHEMA_VERSION = 1
EXTERNAL_RE = re.compile(
    r"\b(github|email|gmail|calendar|drive|google docs|slack|discord|reddit|stripe|payment|analytics|database|sql|post|send|publish|purchase)\b",
    re.I,
)
WRITE_RE = re.compile(r"\b(send|post|publish|submit|delete|charge|refund|purchase|buy|pay|transfer|write|update|modify|invite)\b", re.I)


@dataclass(frozen=True)
class ConnectorDefinition:
    connector_id: str
    label: str
    category: str
    integration_id: str
    required_auth: list[str] = field(default_factory=list)
    required_scopes: list[str] = field(default_factory=list)
    safe_actions: list[str] = field(default_factory=list)
    approval_actions: list[str] = field(default_factory=list)
    blocked_actions: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    setup_command: str = ""


@dataclass(frozen=True)
class ConnectorCard:
    connector_id: str
    label: str
    category: str
    status: str
    ready: bool
    configured: bool
    credential_available: bool
    gateway_available: bool
    required_auth: list[str]
    required_scopes: list[str]
    safe_actions: list[str]
    approval_actions: list[str]
    blocked_actions: list[str]
    setup_command: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CATALOG = (
    ConnectorDefinition(
        "github",
        "GitHub",
        "code",
        "github",
        required_auth=["github"],
        required_scopes=["repo read", "pull requests", "issues", "actions"],
        safe_actions=["inspect repos", "review diffs", "draft issues", "draft PR notes"],
        approval_actions=["push branches", "open PRs", "merge PRs", "rerun CI"],
        aliases=["git", "repo", "pull request", "ci"],
        setup_command="install or enable the GitHub connector, then authenticate the target repo",
    ),
    ConnectorDefinition(
        "email",
        "Email",
        "communications",
        "email",
        required_auth=["email", "gmail", "outlook"],
        required_scopes=["read inbox", "draft email", "send email"],
        safe_actions=["search inbox", "summarize threads", "draft replies"],
        approval_actions=["send email", "modify labels", "delete messages"],
        aliases=["gmail", "outlook", "mail", "inbox"],
        setup_command="connect Gmail or Outlook, or add a credential reference for email",
    ),
    ConnectorDefinition(
        "calendar",
        "Calendar",
        "operations",
        "calendar",
        required_auth=["calendar", "google calendar", "outlook calendar"],
        required_scopes=["read availability", "draft events", "modify calendar"],
        safe_actions=["check availability", "draft events", "summarize schedule"],
        approval_actions=["create events", "move meetings", "cancel meetings"],
        aliases=["meeting", "schedule", "availability"],
        setup_command="connect Google Calendar or Outlook Calendar",
    ),
    ConnectorDefinition(
        "storage",
        "Drive / Storage",
        "files",
        "storage",
        required_auth=["drive", "google drive", "sharepoint", "dropbox"],
        required_scopes=["read files", "draft documents", "write files"],
        safe_actions=["search files", "summarize docs", "draft document changes"],
        approval_actions=["write files", "share files", "delete files"],
        aliases=["drive", "docs", "sheet", "sharepoint", "files"],
        setup_command="connect Google Drive, SharePoint, or a storage connector",
    ),
    ConnectorDefinition(
        "slack",
        "Slack",
        "communications",
        "slack",
        required_auth=["slack"],
        required_scopes=["read channels", "draft messages", "send messages"],
        safe_actions=["search channels", "summarize threads", "draft messages"],
        approval_actions=["send messages", "invite users", "modify channels"],
        aliases=["channel", "team chat"],
        setup_command="connect Slack and approve workspace scopes",
    ),
    ConnectorDefinition(
        "discord",
        "Discord",
        "communications",
        "discord",
        required_auth=["discord"],
        required_scopes=["read servers", "draft posts", "send messages"],
        safe_actions=["summarize servers", "draft posts", "prepare moderation notes"],
        approval_actions=["send messages", "moderate users", "modify channels"],
        aliases=["server", "mod", "community"],
        setup_command="connect Discord or add a safe bot credential reference",
    ),
    ConnectorDefinition(
        "reddit",
        "Reddit",
        "social",
        "reddit",
        required_auth=["reddit"],
        required_scopes=["read posts", "draft posts", "submit posts", "comment"],
        safe_actions=["research subreddits", "draft posts", "draft comments"],
        approval_actions=["submit posts", "comment publicly", "message users"],
        aliases=["subreddit", "karma"],
        setup_command="connect Reddit OAuth or add a credential reference for Reddit",
    ),
    ConnectorDefinition(
        "stripe",
        "Stripe",
        "payments",
        "stripe",
        required_auth=["stripe"],
        required_scopes=["read balances", "draft products", "payments"],
        safe_actions=["read dashboards", "draft product setup", "summarize revenue"],
        approval_actions=["create products", "issue refunds", "change prices"],
        blocked_actions=["charge cards without explicit approval", "move money without explicit approval"],
        aliases=["payments", "checkout", "invoice", "revenue"],
        setup_command="add a Stripe credential reference or connect Stripe",
    ),
    ConnectorDefinition(
        "analytics",
        "Analytics",
        "metrics",
        "analytics",
        required_auth=["analytics", "google analytics", "plausible"],
        required_scopes=["read dashboards", "read funnels"],
        safe_actions=["read dashboards", "summarize funnels", "flag anomalies"],
        approval_actions=["change tracking configuration"],
        aliases=["metrics", "traffic", "funnel"],
        setup_command="connect analytics or add a dashboard credential reference",
    ),
    ConnectorDefinition(
        "database",
        "Database",
        "data",
        "database",
        required_auth=["database", "postgres", "mysql", "sqlite"],
        required_scopes=["read data", "write data"],
        safe_actions=["inspect schema", "draft queries", "run read-only queries"],
        approval_actions=["write data", "drop tables", "migrate schema"],
        blocked_actions=["destructive database changes without backup and explicit approval"],
        aliases=["sql", "postgres", "mysql", "supabase"],
        setup_command="add a reference to the database connection and allowed query scope",
    ),
)


def snapshot(cwd: str | Path, runtime_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(cwd).expanduser().resolve()
    runtime = runtime_snapshot if isinstance(runtime_snapshot, dict) else {}
    integration_rows = runtime.get("integrationsPreview") if isinstance(runtime.get("integrationsPreview"), list) else integrations.snapshot()
    credential_rows = _credential_rows(root, runtime)
    gateway = runtime.get("mcpGateway") if isinstance(runtime.get("mcpGateway"), dict) else mcp_gateway.snapshot(root)
    cards = [_build_card(definition, integration_rows, credential_rows, gateway) for definition in CATALOG]
    ready = [card for card in cards if card.ready]
    needs_auth = [card for card in cards if card.status == "needs-auth"]
    draft_only = [card for card in cards if card.status in {"needs-auth", "needs-setup", "draft-only"}]
    return {
        "schema": SCHEMA_VERSION,
        "total": len(cards),
        "ready": len(ready),
        "needsAuth": len(needs_auth),
        "draftOnly": len(draft_only),
        "cards": [card.to_dict() for card in cards],
        "safeDefaults": [
            "Read/search/summarize is safe when the connector is configured.",
            "Draft public posts, emails, calendar changes, payments, and writes before asking for approval.",
            "Never ask the user to paste raw secrets into chat; create credential references instead.",
        ],
    }


def assess(cwd: str | Path, text: str, runtime_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    data = snapshot(cwd, runtime_snapshot)
    connector = _match_connector(text, data["cards"])
    external = bool(EXTERNAL_RE.search(text or ""))
    wants_write = bool(WRITE_RE.search(text or ""))
    if not connector:
        return {
            "external": external,
            "connector": "",
            "status": "not-detected",
            "ready": False,
            "approvalRequired": wants_write,
            "safeNextStep": "Use normal tools unless the task touches an external account.",
        }
    ready = bool(connector.get("ready"))
    approval_required = wants_write or bool(connector.get("approval_actions"))
    if not ready:
        safe = "Draft the action and record the missing credential/reference before attempting external access."
    elif approval_required:
        safe = "Perform research and drafting first; ask for explicit approval before the external write/send/post."
    else:
        safe = "Read-only connector work is allowed within the configured scopes."
    return {
        "external": True,
        "connector": connector["connector_id"],
        "label": connector["label"],
        "status": connector["status"],
        "ready": ready,
        "approvalRequired": approval_required,
        "safeNextStep": safe,
        "safeActions": connector.get("safe_actions") or [],
        "approvalActions": connector.get("approval_actions") or [],
        "setupCommand": connector.get("setup_command") or "",
    }


def prompt_section(cwd: str | Path, text: str = "", runtime_snapshot: dict[str, Any] | None = None, *, limit: int = 8) -> str:
    data = snapshot(cwd, runtime_snapshot)
    decision = assess(cwd, text, runtime_snapshot) if text else {}
    if not decision and not any(card["status"] != "disabled" for card in data["cards"]):
        return ""
    lines = ["# Connector Readiness"]
    lines.extend(f"- {rule}" for rule in data["safeDefaults"])
    if decision:
        lines.append(
            f"- detected={decision['connector'] or 'none'} status={decision['status']} "
            f"approvalRequired={decision['approvalRequired']}; next={decision['safeNextStep']}"
        )
    for card in data["cards"][: max(1, limit)]:
        actions = ", ".join(card["safe_actions"][:2])
        approval = ", ".join(card["approval_actions"][:2])
        lines.append(f"- {card['label']}: {card['status']}; safe={actions}; approval={approval}")
    return "\n".join(lines)


def _build_card(
    definition: ConnectorDefinition,
    integration_rows: list[dict[str, Any]],
    credential_rows: list[dict[str, Any]],
    gateway: dict[str, Any],
) -> ConnectorCard:
    integration = _integration(integration_rows, definition.integration_id)
    configured = bool(integration.get("configured") or integration.get("enabled"))
    credential_available = _credential_available(credential_rows, definition)
    gateway_available = _gateway_available(gateway, definition)
    ready = configured or credential_available or gateway_available
    if ready:
        status = "ready"
    elif integration and integration.get("status") == "needs-setup":
        status = "needs-setup"
    elif definition.required_auth:
        status = "needs-auth"
    else:
        status = "disabled"
    detail = _detail(definition, configured, credential_available, gateway_available)
    return ConnectorCard(
        connector_id=definition.connector_id,
        label=definition.label,
        category=definition.category,
        status=status,
        ready=ready,
        configured=configured,
        credential_available=credential_available,
        gateway_available=gateway_available,
        required_auth=list(definition.required_auth),
        required_scopes=list(definition.required_scopes),
        safe_actions=list(definition.safe_actions),
        approval_actions=list(definition.approval_actions),
        blocked_actions=list(definition.blocked_actions),
        setup_command=definition.setup_command,
        detail=detail,
    )


def _credential_rows(root: Path, runtime: dict[str, Any]) -> list[dict[str, Any]]:
    vault = runtime.get("credentialVault") if isinstance(runtime.get("credentialVault"), dict) else credential_vault.snapshot(root)
    rows = vault.get("references") if isinstance(vault.get("references"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _integration(rows: list[dict[str, Any]], integration_id: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get("integration_id") or row.get("id") or "") == integration_id:
            return row
    return {}


def _credential_available(rows: list[dict[str, Any]], definition: ConnectorDefinition) -> bool:
    names = {definition.connector_id, definition.integration_id, *definition.required_auth, *definition.aliases}
    lowered = {name.lower() for name in names}
    for row in rows:
        service = str(row.get("service") or "").lower()
        status = str(row.get("status") or "").lower()
        if status == "available" and any(name in service or service in name for name in lowered):
            return True
    return False


def _gateway_available(gateway: dict[str, Any], definition: ConnectorDefinition) -> bool:
    terms = {definition.connector_id, definition.integration_id, *definition.aliases}
    terms = {term.lower() for term in terms if term}
    for server in gateway.get("servers") or []:
        if not isinstance(server, dict):
            continue
        haystack = " ".join(
            [
                str(server.get("name") or ""),
                str(server.get("note") or ""),
                " ".join(str(tool.get("name") or "") + " " + str(tool.get("description") or "") for tool in server.get("tools") or [] if isinstance(tool, dict)),
            ]
        ).lower()
        if any(term in haystack for term in terms) and str(server.get("status") or "") in {"ready", "mock-ready", "configured"}:
            return True
    return False


def _match_connector(text: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
    lowered = (text or "").lower()
    for definition in CATALOG:
        terms = [definition.connector_id, definition.label, definition.integration_id, *definition.aliases]
        if any(str(term).lower() in lowered for term in terms):
            return next((card for card in cards if card["connector_id"] == definition.connector_id), {})
    return {}


def _detail(definition: ConnectorDefinition, configured: bool, credential_available: bool, gateway_available: bool) -> str:
    if configured:
        return "Configured integration is available."
    if credential_available:
        return "Credential reference is available; keep raw secrets out of chat."
    if gateway_available:
        return "Gateway or plugin surface is available."
    return definition.setup_command
