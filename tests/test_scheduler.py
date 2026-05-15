from __future__ import annotations

from pathlib import Path

from core import evidence, goals, scheduler, settings, work_threads


def test_scheduler_runs_one_off_followup_and_records_evidence(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    evidence.clear()
    workspace = tmp_path / "repo"
    workspace.mkdir()
    job = scheduler.schedule_followup(workspace, "Check local tracker", due_at=1)

    run = scheduler.run_due(workspace, now=2)
    refreshed = scheduler.list_jobs(workspace, include_all=True)[0]

    assert run.ran == 1
    assert refreshed.job_id == job.job_id
    assert refreshed.status == "completed"
    assert refreshed.run_count == 1
    assert evidence.entries(kind="schedule")


def test_scheduler_syncs_due_goal_and_updates_thread(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    evidence.clear()
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal("Monitor revenue", workspace=workspace, cadence="daily", success_metric="daily note")
    goals.update_goal(goal.goal_id, next_review_at=1)
    thread = work_threads.ensure_for_goal(goal, prompt_text="Monitor revenue daily")

    run = scheduler.run_due(workspace, now=2)
    job = scheduler.list_jobs(workspace)[0]
    refreshed_goal = goals.list_goals(workspace)[0]
    refreshed_thread = work_threads.list_threads(workspace, include_all=True)[0]

    assert run.ran == 1
    assert job.goal_id == goal.goal_id
    assert job.thread_id == thread.thread_id
    assert job.due_at > 2
    assert refreshed_goal.next_review_at > 2
    assert "Scheduled goal-review reviewed" in refreshed_goal.last_result
    assert refreshed_thread.history[0]["source"] == "scheduler"


def test_scheduler_prompt_section_is_compact(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    scheduler.schedule_followup(workspace, "Review dashboard", cadence="weekly")

    section = scheduler.prompt_section(workspace)

    assert "Scheduler" in section
    assert "Review dashboard" in section
    assert "weekly" in section
