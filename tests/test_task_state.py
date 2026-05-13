from __future__ import annotations

from core import settings, task_state


def test_task_state_records_status_events(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    task = task_state.start_task(
        "fix the parser",
        cwd=workspace,
        provider="fake",
        model="fake-model",
        session_id="session-1",
    )
    task_state.set_status(workspace, task.task_id, "tool_calling", "read_file README.md")
    task_state.set_status(workspace, task.task_id, "completed", "done")

    loaded = task_state.info(workspace, task.task_id)
    assert loaded.status == "completed"
    assert loaded.provider == "fake"
    assert loaded.model == "fake-model"
    assert loaded.session_id == "session-1"
    assert loaded.event_count >= 4

    listed = task_state.list_tasks(workspace)
    assert [item.task_id for item in listed] == [task.task_id]
    rendered = task_state.format_task(workspace, task.task_id)
    assert "fix the parser" in rendered
    assert "completed" in rendered
