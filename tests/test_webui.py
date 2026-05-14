from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from core import settings, webui


def test_webui_snapshot_endpoint(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        assert handler is not None
        snapshot = server.daemon.snapshot()
        assert snapshot["workspace"] == str(workspace.resolve())
    finally:
        server.server_close()


def test_webui_int_helper():
    assert webui._int("12", 1) == 12
    assert webui._int("bad", 7) == 7


def test_webui_event_buffer(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        server.emit_event({"event": "demo", "text": "hello"})
        events = server.events_since(0)
        assert events[0]["event"] == "demo"
        assert json.dumps(events)
    finally:
        server.server_close()


def test_webui_static_is_chat_first():
    html = resources.files("core.webui_static").joinpath("index.html").read_text(encoding="utf-8")
    script = resources.files("core.webui_static").joinpath("app.js").read_text(encoding="utf-8")

    assert "Message Crypt" in html
    assert "Activity" in html
    assert "Skill Forge" not in html
    assert "Start a business" not in html
    assert "planner" not in html
    assert "data-prompt" not in html
    assert "approvalRequested" in script


def test_webui_autonomy_interval(monkeypatch):
    monkeypatch.delenv("CRYPT_WEBUI_AUTONOMY_INTERVAL_SECONDS", raising=False)
    assert webui._autonomy_interval() == webui.DEFAULT_AUTONOMY_INTERVAL_SECONDS

    monkeypatch.setenv("CRYPT_WEBUI_AUTONOMY_INTERVAL_SECONDS", "0")
    assert webui._autonomy_interval() == 0
