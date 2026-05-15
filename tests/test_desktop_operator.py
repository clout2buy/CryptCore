from __future__ import annotations

from pathlib import Path

from core import desktop_operator, desktop_recorder, settings


def test_desktop_operator_plans_visible_actions():
    job = desktop_operator.plan("move the mouse, click settings, and take a screenshot")

    actions = [step.action for step in job.steps]
    assert job.mode == "visual-desktop"
    assert actions[:2] == ["inspect-screen", "move-pointer"]
    assert "click" in actions
    assert "capture-screen" in actions
    assert "Inspect the current visible desktop state" in desktop_operator.narration(job)


def test_desktop_operator_gates_sensitive_actions():
    job = desktop_operator.plan("login and type my password into the app")

    assert job.approval_required is True
    assert job.mode == "approval-gated-desktop"
    assert any(step.requires_approval for step in job.steps if step.action == "type")


def test_desktop_recorder_tracks_actions_screenshots_and_approvals(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    screenshot = workspace / "shots" / "desktop.png"
    screenshot.parent.mkdir()
    screenshot.write_bytes(b"fake")

    job = desktop_operator.plan("login, type my password, and take a screenshot")
    recording = desktop_recorder.create_from_job(workspace, "Login flow", job)
    recording = desktop_recorder.approve_action(workspace, recording.recording_id, "type")
    recording = desktop_recorder.add_screenshot(workspace, recording.recording_id, screenshot, note="before typing")

    assert recording.approval_required is True
    assert any(action.action == "type" and action.approved for action in recording.actions)
    assert recording.screenshots == ["shots/desktop.png"]
    snap = desktop_recorder.snapshot(workspace)
    assert snap["approvalRequired"] == 1
    assert "Desktop Operation Recordings" in desktop_recorder.prompt_section(workspace)
