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
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        web_snapshot = handler_obj._snapshot()
        assert web_snapshot["workspace"] == str(workspace.resolve())
        json.dumps(web_snapshot)
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

    assert "Crypt Workspace" in html
    assert "Core" in html
    assert "composer-shell" in html
    assert "data-intent=\"web\"" in html
    assert "data-view=\"missions\"" in html
    assert "surface-dock" not in html
    assert "Skill Forge" not in html
    assert "Start a business" not in html
    assert "planner" not in html
    assert "data-prompt" not in html
    assert "approvalRequested" in script
    assert "coreFeatures" in script
    assert "renderCurrentView" in script
    assert "Crypt UI intent hints" not in html


def test_webui_core_features_include_hermes_style_sections(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config.json")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    snapshot = {
        "provider": "crypt",
        "model": "crypt-pro",
        "approval": "auto-work",
        "thinkingMode": "fast",
        "providers": [{"label": "Crypt OAuth", "status": "ready"}],
        "routes": [{"role": "builder", "status": "active"}],
        "webui": {"url": "http://127.0.0.1:8765/"},
    }
    features = webui.core_features(workspace, snapshot)
    labels = {feature["label"] for feature in features}

    assert {
        "Chat",
        "Sessions",
        "Profiles",
        "Office",
        "Models",
        "Providers",
        "Skills",
        "Persona",
        "Memory",
        "Tools",
        "Plan",
        "Schedules",
        "Gateway",
        "Settings",
    } <= labels


def test_webui_autonomy_interval(monkeypatch):
    monkeypatch.delenv("CRYPT_WEBUI_AUTONOMY_INTERVAL_SECONDS", raising=False)
    assert webui._autonomy_interval() == webui.DEFAULT_AUTONOMY_INTERVAL_SECONDS

    monkeypatch.setenv("CRYPT_WEBUI_AUTONOMY_INTERVAL_SECONDS", "0")
    assert webui._autonomy_interval() == 0


def test_webui_prompt_intents_are_sanitized():
    assert webui._intent_hints(["web", "bad", "build", "web"]) == ["web", "build"]
    text = webui._prompt_with_intents("Find leads", ["web", "auto"])

    assert text.startswith("Find leads")
    assert "Crypt UI intent hints" in text
    assert "web research" in text
