from __future__ import annotations

from pathlib import Path

from core import external_drafts, goals, notification_center, personal_os, settings, work_threads


def test_personal_os_surface_collects_lanes_actions_and_blockers(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal("Launch client dashboard", workspace=workspace, success_metric="dashboard live")
    thread = work_threads.ensure_for_goal(goal, prompt_text="Build the dashboard")
    work_threads.update_thread(thread.thread_id, state="blocked", next_action="Approve the public launch copy.")
    external_drafts.create_draft(
        workspace,
        kind="reddit-post",
        title="Launch announcement",
        target="reddit",
        content="Draft only",
        source_prompt="announce launch",
        risk="high",
    )
    notification_center.add(workspace, "approval", "Review launch draft", severity="approval")

    surface = personal_os.build(workspace)
    data = surface.to_dict()

    assert data["mode"] == "personal-os"
    assert data["status"] == "attention"
    assert data["summary"]["activeThreads"] == 1
    assert data["summary"]["approvals"] == 1
    assert any(lane["lane_id"] == "approvals" and lane["status"] == "attention" for lane in data["lanes"])
    assert any("Approve the public launch copy" in item for item in data["blockers"])
    assert "Personal OS Mode" in personal_os.prompt_section(workspace)


def test_personal_os_accepts_existing_webui_snapshot(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    data = personal_os.snapshot(
        workspace,
        {
            "goals": [],
            "workThreads": [],
            "notifications": {"unread": 0, "critical": 0, "items": []},
            "externalDrafts": {"pending": 0},
            "jobQueue": {"running": 0, "queued": 0},
            "memoryJournal": {"longTermCount": 3, "openLoopCount": 1},
            "artifactSummary": {"total": 2, "verified": 1, "missionLinked": 1},
            "voice": {"ready": True, "missing": []},
            "missionScheduler": {"due": 0},
            "revenueOps": {"forecast": {"revenue30d": 12}},
        },
    )

    assert data["status"] == "ready"
    assert data["summary"]["activeThreads"] == 0
    assert any(signal["label"] == "Memory" and signal["value"] == "3" for signal in data["signals"])
