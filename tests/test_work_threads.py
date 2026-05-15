from __future__ import annotations

from pathlib import Path

from core import goals, settings, work_threads


def test_work_thread_created_for_business_goal(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal(
        "Build and operate the business",
        description="Start a business and track income weekly.",
        workspace=workspace,
        cadence="weekly",
        tags=["business", "monitor"],
    )

    thread = work_threads.ensure_for_goal(goal, prompt_text=goal.description)

    assert thread.goal_id == goal.goal_id
    assert thread.cadence == "weekly"
    assert "revenue tracker" in thread.next_action
    assert work_threads.list_threads(workspace)[0].thread_id == thread.thread_id


def test_work_thread_marks_external_actions_blocked(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal(
        "Post on Reddit for launch",
        description="Write and post on Reddit for the new product.",
        workspace=workspace,
        tags=["business"],
    )

    thread = work_threads.ensure_for_goal(goal, prompt_text=goal.description)

    assert thread.state == "blocked"
    assert "approval" in thread.blockers[0].lower()
    status = work_threads.status(workspace)
    assert status.blocked == 1


def test_work_thread_reuses_existing_goal_thread(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal("Monitor site revenue", workspace=workspace, cadence="daily")

    first = work_threads.ensure_for_goal(goal, prompt_text="Monitor site revenue daily.")
    second = work_threads.ensure_for_goal(goal, prompt_text="Keep tracking site revenue daily.")

    assert first.thread_id == second.thread_id
    assert len(work_threads.list_threads(workspace, include_all=True)) == 1
