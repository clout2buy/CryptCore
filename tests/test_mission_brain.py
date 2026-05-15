from __future__ import annotations

from pathlib import Path

from core import goals, mission_brain, settings, work_threads


def test_mission_brain_prioritizes_blockers(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal(
        "Post launch update",
        description="Post the launch update on Reddit.",
        workspace=workspace,
    )
    thread = work_threads.ensure_for_goal(goal, prompt_text=goal.description)

    step = mission_brain.plan_thread(thread)

    assert step.kind == "approval_gate"
    assert step.needs_approval is True
    assert "Resolve blocker" in step.action


def test_mission_brain_uses_due_review_before_tasks(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal("Monitor revenue", workspace=workspace, cadence="daily")
    goals.update_goal(goal.goal_id, next_review_at=1)
    due_goal = goals.list_goals(workspace)[0]
    thread = work_threads.ensure_for_goal(due_goal, prompt_text="track income")

    step = mission_brain.plan_thread(thread, now=2)

    assert step.kind == "review"
    assert "Review the latest state" in step.action


def test_mission_brain_review_updates_thread_next_action(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal("Build and operate the business", workspace=workspace, tags=["business"])
    thread = work_threads.ensure_for_goal(goal, prompt_text="start a business")

    steps = mission_brain.review_workspace(workspace)
    refreshed = work_threads.list_threads(workspace)[0]

    assert steps[0].thread_id == thread.thread_id
    assert refreshed.next_action == "Define the offer and target customer"
    assert refreshed.history[0]["source"] == "mission-brain"


def test_mission_brain_prompt_section_is_compact(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal("Build a useful tool", workspace=workspace, tags=["build"])
    work_threads.ensure_for_goal(goal, prompt_text="build an app")

    section = mission_brain.prompt_section(workspace)

    assert "# Mission Brain" in section
    assert "next:" in section
