from __future__ import annotations

from pathlib import Path

from core import autonomy, goals, learning, settings, upgrade_queue, webui, work_threads


def test_upgrade_queue_dedupes_and_ranks_feedback(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    learning.record_user_correction(workspace, "Nope, next time show thinking live before the final answer.")
    learning.record_user_correction(workspace, "Nope, next time show thinking live before the final answer.")
    learning.record_task_outcome(
        cwd=workspace,
        task_id="failed-edit",
        prompt="edit the UI",
        status="failed",
        final_text="schema validation failed: edits must be non-empty",
    )

    first = upgrade_queue.suggest(workspace)
    second = upgrade_queue.suggest(workspace)
    titles = [idea.title for idea in second]

    assert first
    assert len({idea.idea_id for idea in second}) == len(second)
    assert any("user-corrected behavior" in title for title in titles)
    assert any("Harden recovery path" in title for title in titles)
    assert second[0].score >= first[0].score


def test_upgrade_queue_converts_idea_to_mission(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    learning.record_user_correction(workspace, "Actually, make the chat stop flickering while thinking.")
    idea = upgrade_queue.suggest(workspace)[0]

    updated, goal, thread = upgrade_queue.convert_to_mission(workspace, idea.idea_id)

    assert updated.status == "mission"
    assert updated.mission_id == goal.goal_id
    assert goal.title.startswith("Upgrade Crypt:")
    assert thread.goal_id == goal.goal_id
    assert work_threads.list_threads(workspace)
    assert any(item.goal_id == goal.goal_id for item in goals.list_goals(workspace, include_all=True))


def test_autonomy_cycle_refreshes_upgrade_queue(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    learning.record_user_correction(workspace, "Nope, fix the model selector labels next time.")

    cycle = autonomy.run_cycle(workspace)

    assert cycle.upgrade_ideas >= 1
    assert upgrade_queue.list_ideas(workspace)


def test_webui_snapshot_and_prompt_include_upgrade_queue(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    learning.record_user_correction(workspace, "Nope, next time keep the input simple.")
    upgrade_queue.suggest(workspace)

    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        snapshot = handler_obj._snapshot()
    finally:
        server.server_close()
    prompt = webui._prompt_with_context("improve the input", [], workspace=workspace)

    assert snapshot["selfUpgradeQueue"]["count"] >= 1
    assert "Self-Upgrade Queue" in prompt
