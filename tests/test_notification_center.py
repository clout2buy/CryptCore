from __future__ import annotations

from pathlib import Path

from core import notification_center, settings


def test_notification_center_adds_marks_and_snapshots(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    note = notification_center.add(
        workspace,
        "approval",
        "Approval needed",
        body="Send draft email?",
        severity="approval",
        source="test",
        related_id="approval-1",
    )
    snapshot = notification_center.snapshot(workspace)
    read = notification_center.mark_read(note.notification_id)

    assert snapshot["unread"] == 1
    assert snapshot["critical"] == 1
    assert snapshot["items"][0]["title"] == "Approval needed"
    assert read.status == "read"
    assert notification_center.snapshot(workspace)["unread"] == 0


def test_notification_center_prompt_section_only_unread(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    notification_center.add(workspace, "task-failed", "Task failed", severity="error", source="test")
    section = notification_center.prompt_section(workspace)

    assert "# Notification Center" in section
    assert "Task failed" in section
