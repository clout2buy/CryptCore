from __future__ import annotations

import sys
from pathlib import Path

from core import mcp, settings


FAKE_SERVER = r'''
import json
import sys


def decode(data):
    out = []
    pos = 0
    while pos < len(data):
        end = data.find(b"\r\n\r\n", pos)
        if end < 0:
            break
        header = data[pos:end].decode("ascii", errors="ignore")
        length = 0
        for line in header.splitlines():
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        start = end + 4
        body = data[start:start + length]
        out.append(json.loads(body.decode("utf-8")))
        pos = start + length
    return out


def frame(message):
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


messages = decode(sys.stdin.buffer.read())
responses = []
for message in messages:
    method = message.get("method")
    mid = message.get("id")
    if method == "initialize":
        responses.append({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05"}})
    elif method == "tools/list":
        responses.append({
            "jsonrpc": "2.0",
            "id": mid,
            "result": {"tools": [{"name": "echo", "description": "Echo text"}]},
        })
    elif method == "tools/call":
        text = message.get("params", {}).get("arguments", {}).get("text", "")
        responses.append({
            "jsonrpc": "2.0",
            "id": mid,
            "result": {"content": [{"type": "text", "text": "echo:" + text}]},
        })
sys.stdout.buffer.write(b"".join(frame(message) for message in responses))
'''


def _configure(monkeypatch, tmp_path: Path) -> None:
    server = tmp_path / "fake_mcp_server.py"
    server.write_text(FAKE_SERVER, encoding="utf-8")
    monkeypatch.setattr(
        settings,
        "load_config",
        lambda: {
            "mcp_servers": {
                "fake": {
                    "command": sys.executable,
                    "args": [str(server)],
                    "framing": "headers",
                }
            }
        },
    )


def test_mcp_lists_configured_servers(monkeypatch, tmp_path: Path):
    _configure(monkeypatch, tmp_path)

    summary = mcp.server_summary()

    assert "fake:" in summary


def test_mcp_lists_tools(monkeypatch, tmp_path: Path):
    _configure(monkeypatch, tmp_path)

    result = mcp.list_tools("fake")

    assert result["tools"][0]["name"] == "echo"
    assert "Echo text" in mcp.format_tool_list(result)


def test_mcp_calls_tool(monkeypatch, tmp_path: Path):
    _configure(monkeypatch, tmp_path)

    result = mcp.call_tool("fake", "echo", {"text": "hello"})

    assert mcp.format_call_result(result) == "echo:hello"


def test_mcp_server_env_scrubs_ambient_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    monkeypatch.setenv("PATH", "safe-path")

    cfg = mcp.McpServerConfig(
        name="fake",
        command=sys.executable,
        env={"SERVER_TOKEN": "explicit-token"},
    )

    env = mcp._server_env(cfg)

    assert env["PATH"] == "safe-path"
    assert env["SERVER_TOKEN"] == "explicit-token"
    assert "OPENAI_API_KEY" not in env
    assert "secret-key" not in env.values()
