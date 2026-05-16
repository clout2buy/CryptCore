from __future__ import annotations

from pathlib import Path

from core import browser_recorder, desktop_recorder, operator_hud, settings


def test_operator_hud_reports_browser_and_desktop_boundaries(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    browser = browser_recorder.start_recording(workspace, "http://127.0.0.1:8765/", title="Crypt")
    browser_recorder.add_note(workspace, browser.recording_id, "Opened local WebUI.")
    desktop_recorder.create_from_prompt(workspace, "click the post button")

    snapshot = operator_hud.snapshot(workspace)
    browser_channel = next(channel for channel in snapshot["channels"] if channel["channel"] == "browser")
    desktop_channel = next(channel for channel in snapshot["channels"] if channel["channel"] == "desktop")

    assert snapshot["status"] == "active"
    assert browser_channel["target"] == "http://127.0.0.1:8765/"
    assert "Opened local WebUI" in browser_channel["last_action"]
    assert desktop_channel["status"] == "blocked"
    assert "approval" in desktop_channel["approval_boundary"].lower()
    assert "Operator HUD" in operator_hud.prompt_section(workspace)


def test_operator_hud_idle_without_recordings(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    snapshot = operator_hud.snapshot(workspace)

    assert snapshot["status"] == "idle"
    assert snapshot["active"] == 0
    assert {channel["channel"] for channel in snapshot["channels"]} == {"browser", "desktop"}
