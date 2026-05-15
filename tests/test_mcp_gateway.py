from __future__ import annotations

from pathlib import Path

from core import mcp_gateway, settings, webui


def test_mcp_gateway_registers_mock_server_and_tool_call(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config.json")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    server = mcp_gateway.register_mock_server(
        workspace,
        "design-lab",
        tools=[
            {
                "name": "render_preview",
                "description": "Render local UI preview",
                "capability": "browser",
            }
        ],
    )
    servers = mcp_gateway.list_servers(workspace)
    tools = mcp_gateway.list_tools(workspace, "design-lab")
    result = mcp_gateway.call_mock_tool(workspace, "design-lab", "render_preview", {"url": "http://127.0.0.1"})

    assert server.status == "mock-ready"
    assert servers[0].name == "design-lab"
    assert tools[0].permission_label == "safe-local"
    assert result.ok is True
    assert "render_preview" in result.output


def test_mcp_gateway_health_and_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config.json")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    mcp_gateway.register_mock_server(workspace, "ops", tools=[{"name": "list_jobs", "description": "List queued jobs"}])

    health = mcp_gateway.health_check(workspace, "ops")
    snapshot = mcp_gateway.snapshot(workspace)
    section = mcp_gateway.prompt_section(workspace)

    assert health.status == "mock-ready"
    assert snapshot["count"] == 1
    assert snapshot["servers"][0]["tools"][0]["risk"] == "safe"
    assert "MCP And Plugin Gateway" in section
    assert "ops" in section


def test_webui_snapshot_includes_mcp_gateway(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config.json")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    mcp_gateway.register_mock_server(workspace, "mock-browser", tools=[{"name": "open_page"}])

    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        snapshot = handler_obj._snapshot()
    finally:
        server.server_close()

    assert snapshot["mcpGateway"]["count"] == 1
    assert snapshot["mcpGateway"]["servers"][0]["name"] == "mock-browser"
