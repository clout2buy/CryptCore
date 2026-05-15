from __future__ import annotations

from pathlib import Path

from core import evidence, goals, monitors, settings, work_threads


def test_mock_monitor_detects_change_and_updates_mission(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    evidence.clear()
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal("Watch revenue", workspace=workspace, success_metric="change noticed")
    thread = work_threads.ensure_for_goal(goal, prompt_text="Watch revenue dashboard")
    monitor = monitors.add_monitor(
        workspace,
        "Revenue total",
        kind="mock",
        target="revenue",
        goal_id=goal.goal_id,
        thread_id=thread.thread_id,
    )

    first = monitors.check_monitor(workspace, monitor, probe_values={"revenue": "$10"})
    refreshed = monitors.list_monitors(workspace)[0]
    second = monitors.check_monitor(workspace, refreshed, probe_values={"revenue": "$12"})
    refreshed_goal = goals.list_goals(workspace)[0]
    refreshed_thread = work_threads.list_threads(workspace, include_all=True)[0]

    assert first.changed is False
    assert second.changed is True
    assert "Monitor changed" in refreshed_goal.last_result
    assert refreshed_thread.history[0]["source"] == "monitor-framework"
    assert evidence.entries(kind="monitor")


def test_file_monitor_tracks_workspace_file_changes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    target = workspace / "stats.txt"
    target.write_text("one\n", encoding="utf-8")
    monitor = monitors.add_monitor(workspace, "Stats file", kind="file", target="stats.txt")

    first = monitors.check_monitor(workspace, monitor)
    target.write_text("two\n", encoding="utf-8")
    refreshed = monitors.list_monitors(workspace)[0]
    second = monitors.check_monitor(workspace, refreshed)

    assert first.changed is False
    assert second.changed is True


def test_monitors_prompt_section(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    monitors.add_monitor(workspace, "Price watch", kind="mock", target="price")

    section = monitors.prompt_section(workspace)

    assert "Monitors" in section
    assert "Price watch" in section
