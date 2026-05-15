from __future__ import annotations

import threading
from pathlib import Path

from core import browser_operator, browser_recorder, settings, webui


def test_browser_operator_plans_local_visual_qa():
    plan = browser_operator.plan("Open the WebUI on 127.0.0.1 and take a desktop screenshot")

    assert plan.mode == "local-app-qa"
    assert "local-qa" in plan.actions
    assert "screenshot" in plan.actions
    assert plan.needs_visual_browser is True


def test_browser_operator_local_smoke_checks_webui(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        result = browser_operator.local_smoke(f"http://{host}:{port}/")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.ok is True
    assert result.status == 200
    assert result.title == "Crypt"
    assert {"http", "html", "title"} <= set(result.checks)


def test_browser_operator_builds_approval_gated_form_job():
    job = browser_operator.build_job("Fill the signup form and post the draft to Reddit", target="https://example.com")

    assert job.approval_required is True
    assert job.job_type == "approval-gated-browser-job"
    assert "form-draft" in job.evidence_required
    assert "approval" in job.evidence_required
    gated = [step for step in job.steps if step.requires_approval]
    assert gated
    assert browser_operator.step_allowed(gated[0], approved=False) is False
    assert browser_operator.step_allowed(gated[0], approved=True) is True


def test_browser_recorder_tracks_smoke_screenshots_and_console(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    screenshot = workspace / "shots" / "home.png"
    screenshot.parent.mkdir()
    screenshot.write_bytes(b"fakepng")

    result = browser_operator.BrowserSmokeResult(
        url="http://127.0.0.1:8765/",
        ok=True,
        status=200,
        title="Crypt",
        bytes_read=1200,
        checks=["http", "html", "title"],
    )
    recording = browser_recorder.record_smoke(workspace, result)
    recording = browser_recorder.add_screenshot(workspace, recording.recording_id, screenshot)
    recording = browser_recorder.add_console_error(workspace, recording.recording_id, "ReferenceError: demo")

    assert recording.status == "failed"
    assert recording.screenshots == ["shots/home.png"]
    assert recording.console_errors == ["ReferenceError: demo"]
    snap = browser_recorder.snapshot(workspace)
    assert snap["total"] == 1
    assert snap["failed"] == 1
    assert "Browser Visual Recordings" in browser_recorder.prompt_section(workspace)
