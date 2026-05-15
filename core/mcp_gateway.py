"""MCP/plugin gateway visibility and health layer."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import mcp, session, settings


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GatewayTool:
    name: str
    description: str = ""
    capability: str = "general"
    permission_label: str = "approval-required"
    risk: str = "external"


@dataclass(frozen=True)
class GatewayServer:
    name: str
    status: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    source: str = "config"
    permission_label: str = "approval-required"
    tools: list[GatewayTool] = field(default_factory=list)
    last_checked_at: int = 0
    note: str = ""


@dataclass(frozen=True)
class GatewayCallResult:
    server: str
    tool: str
    ok: bool
    output: str


def state_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "gateway" / "mcp_gateway.json"


def register_mock_server(
    cwd: str | Path,
    name: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    note: str = "",
) -> GatewayServer:
    clean_name = _clean_name(name)
    if not clean_name:
        raise ValueError("server name is required")
    server = GatewayServer(
        name=clean_name,
        status="mock-ready",
        command="mock",
        source="mock",
        permission_label="safe-local",
        tools=[_tool_from_dict(item, default_permission="safe-local", default_risk="safe") for item in tools or []],
        last_checked_at=_now(),
        note=_clean(note, 300),
    )
    state = _read(cwd)
    servers = [item for item in state.get("mock_servers", []) if item.get("name") != clean_name]
    servers.insert(0, asdict(server))
    state["mock_servers"] = servers[:50]
    _write(cwd, state)
    return server


def list_servers(cwd: str | Path, *, probe: bool = False) -> list[GatewayServer]:
    servers: list[GatewayServer] = []
    for name, cfg in sorted(mcp.configured_servers().items()):
        tools: list[GatewayTool] = []
        status = "configured"
        note = ""
        checked = 0
        if probe:
            checked = _now()
            try:
                result = mcp.list_tools(name, timeout=2)
            except Exception as exc:
                status = "unhealthy"
                note = f"{type(exc).__name__}: {exc}"
            else:
                status = "ready"
                tools = [_tool_from_mcp(item) for item in result.get("tools", []) if isinstance(item, dict)]
                note = f"{len(tools)} tool(s)"
        servers.append(
            GatewayServer(
                name=name,
                status=status,
                command=cfg.command,
                args=list(cfg.args),
                source="config",
                permission_label="approval-required",
                tools=tools,
                last_checked_at=checked,
                note=note,
            )
        )
    for item in _read(cwd).get("mock_servers", []):
        if isinstance(item, dict):
            servers.append(_server_from_dict(item))
    servers.sort(key=lambda item: (item.source != "mock", item.name.lower()))
    return servers


def health_check(cwd: str | Path, name: str) -> GatewayServer:
    clean = _clean_name(name)
    mock = next((server for server in list_servers(cwd) if server.name == clean and server.source == "mock"), None)
    if mock:
        return replace(mock, status="mock-ready", last_checked_at=_now())
    return next((server for server in list_servers(cwd, probe=True) if server.name == clean), GatewayServer(name=clean, status="missing"))


def list_tools(cwd: str | Path, server_name: str) -> list[GatewayTool]:
    server = next((item for item in list_servers(cwd, probe=False) if item.name == server_name), None)
    if server is None:
        return []
    if server.source == "mock":
        return server.tools
    try:
        result = mcp.list_tools(server.name, timeout=5)
    except Exception:
        return []
    return [_tool_from_mcp(item) for item in result.get("tools", []) if isinstance(item, dict)]


def call_mock_tool(cwd: str | Path, server_name: str, tool_name: str, arguments: dict[str, Any] | None = None) -> GatewayCallResult:
    server = next((item for item in list_servers(cwd) if item.name == server_name and item.source == "mock"), None)
    if server is None:
        raise KeyError(f"mock server not found: {server_name}")
    tool = next((item for item in server.tools if item.name == tool_name), None)
    if tool is None:
        raise KeyError(f"mock tool not found: {tool_name}")
    return GatewayCallResult(
        server=server.name,
        tool=tool.name,
        ok=True,
        output=json.dumps({"server": server.name, "tool": tool.name, "arguments": arguments or {}}, sort_keys=True),
    )


def snapshot(cwd: str | Path, *, probe: bool = False) -> dict[str, Any]:
    servers = list_servers(cwd, probe=probe)
    return {
        "path": str(state_path(cwd)),
        "count": len(servers),
        "servers": [asdict(server) for server in servers],
    }


def prompt_section(cwd: str | Path, *, limit: int = 8) -> str:
    servers = list_servers(cwd)[: max(1, limit)]
    if not servers:
        return ""
    lines = ["# MCP And Plugin Gateway"]
    for server in servers:
        lines.append(f"- {server.name}: {server.status}; permission={server.permission_label}; tools={len(server.tools)}")
    return "\n".join(lines)


def _read(cwd: str | Path) -> dict[str, Any]:
    path = state_path(cwd)
    if not path.exists():
        return {"schema": SCHEMA_VERSION, "mock_servers": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": SCHEMA_VERSION, "mock_servers": []}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return {"schema": SCHEMA_VERSION, "mock_servers": []}
    data.setdefault("mock_servers", [])
    return data


def _write(cwd: str | Path, state: dict[str, Any]) -> None:
    path = state_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["schema"] = SCHEMA_VERSION
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    settings.restrict_file_permissions(path)


def _server_from_dict(item: dict[str, Any]) -> GatewayServer:
    return GatewayServer(
        name=_clean_name(item.get("name")),
        status=_clean(item.get("status", "mock-ready"), 40),
        command=_clean(item.get("command", "mock"), 160),
        args=[str(arg) for arg in item.get("args", []) if str(arg).strip()],
        source=_clean(item.get("source", "mock"), 40),
        permission_label=_clean(item.get("permission_label", "safe-local"), 80),
        tools=[_tool_from_dict(tool, default_permission="safe-local", default_risk="safe") for tool in item.get("tools", []) if isinstance(tool, dict)],
        last_checked_at=int(item.get("last_checked_at") or 0),
        note=_clean(item.get("note", ""), 300),
    )


def _tool_from_mcp(item: dict[str, Any]) -> GatewayTool:
    name = str(item.get("name") or "")
    description = str(item.get("description") or "")
    return GatewayTool(
        name=name,
        description=_clean(description, 500),
        capability=_capability(name, description),
        permission_label=_permission_label(name, description),
        risk=_risk(name, description),
    )


def _tool_from_dict(item: dict[str, Any], *, default_permission: str, default_risk: str) -> GatewayTool:
    return GatewayTool(
        name=_clean_name(item.get("name")),
        description=_clean(item.get("description", ""), 500),
        capability=_clean(item.get("capability", "general"), 80),
        permission_label=_clean(item.get("permission_label", default_permission), 80),
        risk=_clean(item.get("risk", default_risk), 80),
    )


def _capability(name: str, description: str) -> str:
    text = f"{name} {description}".lower()
    if any(term in text for term in ("browser", "web", "url", "search")):
        return "browser"
    if any(term in text for term in ("file", "read", "write", "document")):
        return "files"
    if any(term in text for term in ("email", "slack", "discord", "reddit", "post")):
        return "communications"
    if any(term in text for term in ("database", "sql", "query")):
        return "data"
    return "general"


def _risk(name: str, description: str) -> str:
    text = f"{name} {description}".lower()
    if any(term in text for term in ("write", "delete", "send", "post", "publish", "payment", "purchase")):
        return "external-write"
    if any(term in text for term in ("read", "search", "list", "fetch")):
        return "read-only"
    return "external"


def _permission_label(name: str, description: str) -> str:
    risk = _risk(name, description)
    if risk == "read-only":
        return "read-only"
    return "approval-required"


def _clean_name(value: object) -> str:
    clean = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in str(value or "").strip())
    return clean.strip(".-")[:80]


def _clean(value: object, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
