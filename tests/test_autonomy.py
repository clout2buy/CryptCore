from __future__ import annotations

from pathlib import Path

from core import autonomy, evidence, goals, learning, reflection, settings, skill_forge


def test_autonomy_cycle_reflects_and_reviews_due_goals(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    evidence.clear()
    try:
        evidence.record_tool_result("edit_file", {"path": "core/app.py"}, ok=True, output="edited", task_id="task-1")
        evidence.record_tool_result(
            "bash",
            {"command": "python -m pytest tests/test_app.py"},
            ok=True,
            output="1 passed",
            task_id="task-1",
        )
        learning.record_task_outcome(
            cwd=workspace,
            task_id="task-1",
            prompt="fix app",
            status="completed",
            final_text="done",
        )
        goal = goals.add_goal(
            "Improve Crypt reliability",
            workspace=workspace,
            success_metric="quick verification passes",
            cadence="daily",
        )
        goals.update_goal(goal.goal_id, next_review_at=1)

        cycle = autonomy.run_cycle(workspace)

        assert cycle.reflected >= 1
        assert cycle.goal_reviews == 1
        assert cycle.lessons_added >= 1
        assert autonomy.list_cycles(workspace)[0].cycle_id == cycle.cycle_id
        assert reflection.list_reflections(workspace)
        assert any("Improve Crypt reliability" in lesson.text for lesson in learning.list_lessons(workspace))
    finally:
        evidence.clear()


def test_skill_forge_creates_project_skill_from_lessons(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    learning.add_lesson(
        "For release work, run scripts/verify_core.ps1 -Quick.",
        cwd=workspace,
        scope="project",
        tags=["release", "verification"],
        confidence=0.8,
    )
    learning.add_lesson(
        "For release work, inspect docs/REFERENCE.md before pushing.",
        cwd=workspace,
        scope="project",
        tags=["release", "docs"],
        confidence=0.7,
    )

    result = skill_forge.forge_skill(workspace, topic="release", min_lessons=2)

    assert result.skill_name == "release"
    assert result.path.exists()
    text = result.path.read_text(encoding="utf-8")
    assert "scripts/verify_core.ps1" in text
    assert "docs/REFERENCE.md" in text
