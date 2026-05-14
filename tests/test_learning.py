from __future__ import annotations

from pathlib import Path

from core import evidence, learning, prompt, runtime, settings
from tools import registry


class _Provider:
    name = "doctor"
    model = "doctor"


def test_learning_records_episode_and_project_lessons(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence.clear()
    try:
        evidence.record_tool_result("edit_file", {"path": "core/example.py"}, ok=True, output="edited", task_id="task-1")
        evidence.record_tool_result(
            "bash",
            {"command": "python -m pytest tests/test_example.py"},
            ok=True,
            output="1 passed",
            task_id="task-1",
        )

        result = learning.record_task_outcome(
            cwd=workspace,
            task_id="task-1",
            prompt="fix the example parser",
            status="completed",
            final_text="Implemented and verified.",
            provider="fake",
            model="fake-model",
            session_id="session-1",
        )

        assert result["lesson_count"] >= 2
        lessons = learning.list_lessons(workspace)
        assert any("python -m pytest tests/test_example.py" in lesson.text for lesson in lessons)
        assert any("core" in lesson.text for lesson in lessons)

        episodes = learning.list_episodes(workspace)
        assert episodes[0].task_id == "task-1"
        assert episodes[0].changed_paths == ["core/example.py"]
        assert episodes[0].verification_commands == ["python -m pytest tests/test_example.py"]
    finally:
        evidence.clear()


def test_learning_prompt_retrieves_relevant_lessons(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    learning.add_lesson(
        "For parser fixes, run python -m pytest tests/test_parser.py.",
        cwd=workspace,
        scope="project",
        tags=["parser", "verification"],
    )

    section = learning.prompt_section(workspace, "parser fix")

    assert "# Learned Context" in section
    assert "tests/test_parser.py" in section


def test_prompt_includes_learned_context(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    learning.add_lesson("Use the local smoke suite for release checks.", cwd=workspace, scope="project")

    runtime.configure(_Provider(), str(workspace))
    text = prompt.build_system_prompt(
        provider_name="doctor",
        model="doctor",
        cwd=str(workspace),
        tool_guidance="",
        learning_query="release checks",
    )

    assert "# Learned Context" in text
    assert "local smoke suite" in text
    assert "# Crypt Soul" in text
    assert "Do not claim literal sentience" in text
    assert "# Autopilot Behavior" in text
    assert "The user should not need to know tool names" in text
    assert "prompt recipes" in text


def test_learn_tool_search_and_add(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    runtime.configure(_Provider(), str(workspace))

    ok, added = registry.dispatch(
        "learn",
        {"action": "add", "text": "When docs change, update docs/REFERENCE.md.", "scope": "project"},
        render=False,
    )
    assert ok is False
    assert "approval required" in added

    previous = runtime.approval_mode()
    runtime.set_approval_mode(runtime.APPROVAL_ALL)
    try:
        ok, added = registry.dispatch(
            "learn",
            {"action": "add", "text": "When docs change, update docs/REFERENCE.md.", "scope": "project"},
            render=False,
        )
        assert ok is True
        assert "learned" in added
    finally:
        runtime.set_approval_mode(previous)

    ok, output = registry.dispatch("learn", {"action": "search", "query": "docs"}, render=False)

    assert ok is True
    assert "docs/REFERENCE.md" in output
