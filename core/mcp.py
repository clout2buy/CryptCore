"""Minimal stdio MCP client helpers.

Crypt exposes MCP through a conservative generic tool. Servers are configured
in ``~/.crypt/config.json`` under ``mcp_servers``:

    {
      "mcp_servers": {
        "demo": {
          "command": "python",
          "args": ["server.py"],
          "env": {"TOKEN": "..."},
          "framing": "headers"
        }
      }
    }

The implementation is intentionally one-shot: each list/call starts the server,
sends initialize plus the requested method, closes stdin, reads responses, and
exits. That keeps process lifetime, credentials, and approval behavior simple.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import redact, settings


PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 30
SAFE_ENV_KEYS = {
    "PATH",
    "PATHEXT",
    "HOME",
    "USER",
    "USERNAME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
}


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    cwd: str | None = None
    framing: str = "headers"

    @property
    def argv(self) -> list[str]:
        if self.args:
            return [self.command, *self.args]
        return _command_argv(self.command)


def configured_servers(saved: dict | None = None) -> dict[str, McpServerConfig]:
    saved = settings.load_config() if saved is None else saved
    raw = saved.get("mcp_servers") or saved.get("mcpServers") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, McpServerConfig] = {}
    for name, value in raw.items():
        if not isinstance(value, dict):
            continue
        command = str(value.get("command") or "").strip()
        if not command:
            continue
        args = value.get("args") or []
        env = value.get("env") or None
        if not isinstance(args, list):
            args = []
        if not isinstance(env, dict):
            env = None
        framing = str(value.get("framing") or "headers").strip().lower()
        if framing not in {"headers", "jsonl"}:
            framing = "headers"
        cwd = str(value.get("cwd") or "").strip() or None
        out[str(name)] = McpServerConfig(
            name=str(name),
            command=command,
            args=tuple(str(item) for item in args),
            env={str(k): str(v) for k, v in env.items()} if env else None,
            cwd=cwd,
            framing=framing,
        )
    return out


def server_summary(saved: dict | None = None) -> str:
    servers = configured_servers(saved)
    if not servers:
        return "no MCP servers configured"
    lines = []
    for name, cfg in sorted(servers.items()):
        argv = " ".join(cfg.argv)
        lines.append(f"{name}: {argv} ({cfg.framing})")
    return "\n".join(lines)


def list_tools(server_name: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    cfg = _server(server_name)
    response = _request(cfg, "tools/list", {}, timeout=timeout)
    result = _result_or_raise(response)
    return result if isinstance(result, dict) else {"tools": []}


def call_tool(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    cfg = _server(server_name)
    response = _request(
        cfg,
        "tools/call",
        {"name": tool_name, "arguments": arguments or {}},
        timeout=timeout,
    )
    result = _result_or_raise(response)
    return result if isinstance(result, dict) else {"content": result}


def format_tool_list(result: dict[str, Any]) -> str:
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list) or not tools:
        return "(no tools)"
    lines = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        desc = str(item.get("description") or "")
        lines.append(f"- {name}: {desc}".rstrip())
    return "\n".join(lines) or "(no tools)"


def format_call_result(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return str(result)
    content = result.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        if parts:
            return "\n".join(parts)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _server(name: str) -> McpServerConfig:
    servers = configured_servers()
    cfg = servers.get(name)
    if cfg is None:
        available = ", ".join(sorted(servers)) or "none"
        raise KeyError(f"unknown MCP server {name!r}; configured: {available}")
    return cfg


def _request(
    cfg: McpServerConfig,
    method: str,
    params: dict[str, Any],
    *,
    timeout: int,
) -> dict[str, Any]:
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "crypt", "version": settings.CRYPT_VERSION},
        },
    }
    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    target = {"jsonrpc": "2.0", "id": 2, "method": method, "params": params}
    payload = b"".join(_encode_message(msg, cfg.framing) for msg in (init, initialized, target))
    stdout, stderr = _run(cfg, payload, timeout=timeout)
    messages = _decode_messages(stdout)
    for message in messages:
        if isinstance(message, dict) and message.get("id") == 2:
            return message
    stderr_text = redact.text(stderr.decode("utf-8", errors="replace").strip())
    raise RuntimeError(f"MCP server {cfg.name} returned no response for {method}: {stderr_text}")


def _run(cfg: McpServerConfig, payload: bytes, *, timeout: int) -> tuple[bytes, bytes]:
    env = _server_env(cfg)
    try:
        proc = subprocess.Popen(
            cfg.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(cfg.cwd).expanduser()) if cfg.cwd else None,
            env=env,
        )
    except OSError as exc:
        raise RuntimeError(f"failed to start MCP server {cfg.name}: {exc}") from exc
    try:
        stdout, stderr = proc.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        stdout, stderr = proc.communicate()
        detail = redact.text((stderr or b"").decode("utf-8", errors="replace").strip())
        raise TimeoutError(f"MCP server {cfg.name} timed out after {timeout}s: {detail}") from exc
    if proc.returncode not in (0, None):
        # Some servers exit non-zero after stdin closes despite producing a
        # valid response, so callers parse stdout first. Only fail immediately
        # when stdout is empty.
        if not stdout.strip():
            detail = redact.text((stderr or b"").decode("utf-8", errors="replace").strip())
            raise RuntimeError(f"MCP server {cfg.name} exited {proc.returncode}: {detail}")
    return stdout or b"", stderr or b""


def _server_env(cfg: McpServerConfig) -> dict[str, str]:
    env = {
        key.upper(): value
        for key, value in os.environ.items()
        if key.upper() in SAFE_ENV_KEYS and value
    }
    if cfg.env:
        env.update(cfg.env)
    return env


def _encode_message(message: dict[str, Any], framing: str) -> bytes:
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if framing == "jsonl":
        return body + b"\n"
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _decode_messages(data: bytes) -> list[Any]:
    if not data.strip():
        return []
    if b"Content-Length:" in data[:200]:
        return _decode_header_messages(data)
    out = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line.decode("utf-8", errors="replace")))
        except json.JSONDecodeError:
            continue
    return out


def _decode_header_messages(data: bytes) -> list[Any]:
    out: list[Any] = []
    pos = 0
    while pos < len(data):
        header_end = data.find(b"\r\n\r\n", pos)
        sep_len = 4
        if header_end < 0:
            header_end = data.find(b"\n\n", pos)
            sep_len = 2
        if header_end < 0:
            break
        header = data[pos:header_end].decode("ascii", errors="ignore")
        length = 0
        for line in header.splitlines():
            if line.lower().startswith("content-length:"):
                try:
                    length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    length = 0
        body_start = header_end + sep_len
        body_end = body_start + length
        if length <= 0 or body_end > len(data):
            break
        try:
            out.append(json.loads(data[body_start:body_end].decode("utf-8", errors="replace")))
        except json.JSONDecodeError:
            pass
        pos = body_end
        while pos < len(data) and data[pos] in b"\r\n":
            pos += 1
    return out


def _result_or_raise(response: dict[str, Any]) -> Any:
    if "error" in response:
        error = response["error"]
        if isinstance(error, dict):
            message = error.get("message") or json.dumps(error, ensure_ascii=False)
        else:
            message = str(error)
        raise RuntimeError(f"MCP error: {message}")
    return response.get("result", {})


def _command_argv(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return [command]
