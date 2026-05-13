from __future__ import annotations

from core import mcp

from .fs import int_arg
from .types import Tool


def run(args: dict) -> str:
    action = str(args.get("action") or "servers").strip().lower()
    if action == "servers":
        return mcp.server_summary()

    server = str(args.get("server") or "").strip()
    if not server:
        raise ValueError("server is required")
    timeout = int_arg(args, "timeout", 30, 120)

    if action == "tools":
        return mcp.format_tool_list(mcp.list_tools(server, timeout=timeout))
    if action == "call":
        tool = str(args.get("tool") or "").strip()
        if not tool:
            raise ValueError("tool is required for action=call")
        arguments = args.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        return mcp.format_call_result(mcp.call_tool(server, tool, arguments, timeout=timeout))
    raise ValueError("action must be servers, tools, or call")


def classify(args: dict) -> str | None:
    if str(args.get("action") or "servers").strip().lower() == "servers":
        return "safe"
    return None


def summary(args: dict) -> str:
    action = str(args.get("action") or "servers").strip().lower()
    server = str(args.get("server") or "")
    tool = str(args.get("tool") or "")
    if action == "call":
        return f"mcp {server}.{tool}".strip()
    if action == "tools":
        return f"mcp tools {server}".strip()
    return "mcp servers"


PROMPT = """
Bridge to configured MCP stdio servers.

Use action=servers to inspect configured servers. Use action=tools to list a
server's tools. Use action=call with a server, tool name, and JSON arguments to
invoke a tool. MCP server commands come from ~/.crypt/config.json and may start
external processes, so tools/call operations require approval.
""".strip()


TOOL = Tool(
    "mcp",
    "List or call tools on configured MCP stdio servers.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["servers", "tools", "call"]},
            "server": {"type": "string"},
            "tool": {"type": "string"},
            "arguments": {"type": "object"},
            "timeout": {"type": "integer"},
        },
        "required": ["action"],
    },
    "ask",
    run,
    prompt=PROMPT,
    priority=95,
    summary=summary,
    classify=classify,
    available_in_subagent=False,
)
