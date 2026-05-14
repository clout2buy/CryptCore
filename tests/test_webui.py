from __future__ import annotations

import json
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
