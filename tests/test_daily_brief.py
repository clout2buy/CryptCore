from __future__ import annotations

import time
from pathlib import Path

from core import credential_vault, daily_brief, goals, notification_center, scheduler, settings, work_threads


def test_daily_brief_summarizes_missions_approvals_and_reminders(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    now = int(time.time())
    goal = goals.add_goal(
        "Launch tiny product",
        workspace=workspace,
        cadence="daily",
        success_metric="first checkout link ready",
    )
    goals.update_goal(goal.goal_id, next_review_at=now - 5)
    work_threads.ensure_for_goal(goal, prompt_text="post launch update to reddit")
    scheduler.schedule_followup(workspace, "Check product launch", prompt="Review launch state", due_at=now - 10)
    notification_center.add(workspace, "approval", "Approve launch post", body="External post needs approval", severity="approval")
    credential_vault.add_reference(workspace, service="reddit", purpose="submit launch post", status="needed")

    brief = daily_brief.build(workspace, now=now)

    assert brief.open_missions
    assert brief.approvals
    assert brief.reminders
    assert brief.next_actions
    assert "Crypt Daily Brief" in daily_brief.to_markdown(brief)


def test_daily_brief_writes_latest_markdown(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    written = daily_brief.write_brief(workspace, now=1_800_000_000)

    assert Path(written["path"]).exists()
    assert Path(written["latestPath"]).exists()
    assert written["counts"]["nextActions"] >= 1
    assert "Daily Brief" in daily_brief.prompt_section(workspace)
