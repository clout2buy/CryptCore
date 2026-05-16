from __future__ import annotations

from pathlib import Path

from core import safety_incidents, settings


def test_safety_incidents_detect_secret_and_dangerous_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    incidents = safety_incidents.observe_prompt(
        workspace,
        "Use sk-abc123abc123abc123abc123 and then run rm -rf on the repo.",
    )
    snap = safety_incidents.snapshot(workspace)

    assert len(incidents) == 2
    assert snap["open"] == 2
    assert snap["critical"] == 2
    assert snap["byKind"]["secret-detected"] == 1
    assert snap["byKind"]["dangerous-prompt"] == 1
    assert "Safety Incident Log" in safety_incidents.prompt_section(workspace)


def test_safety_incidents_status_update(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    incident = safety_incidents.record(
        workspace,
        kind="approval-denied",
        severity="warning",
        title="Denied publish",
        detail="User said no.",
    )

    updated = safety_incidents.mark_status(workspace, incident.incident_id, status="reviewed")

    assert updated.status == "reviewed"
    assert safety_incidents.snapshot(workspace)["open"] == 0
