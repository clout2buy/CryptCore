from __future__ import annotations

from pathlib import Path

from core import autonomy, evidence, goals, learning, memory_journal, persona_governance, reflection, settings, skill_forge, soul


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
        assert soul.soul_path().exists()
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
    assert result.validated is True
    assert result.path.exists()
    text = result.path.read_text(encoding="utf-8")
    assert "scripts/verify_core.ps1" in text
    assert "docs/REFERENCE.md" in text
    assert "smoke_tests:" in text


def test_soul_evolves_from_preference_lessons(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    learning.add_lesson(
        "User prefers Crypt to sound natural and not robotic.",
        cwd=workspace,
        scope="project",
        tags=["voice", "preference"],
        confidence=0.85,
    )

    update = soul.evolve(workspace)
    text = soul.read_soul()

    assert update.changed is True
    assert update.preference_count == 1
    assert "User prefers Crypt to sound natural" in text
    assert "Do not claim literal sentience" in text


def test_soul_evolves_from_typed_persona_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    memory_journal.observe(
        workspace,
        "Crypt should be sassy, blunt, smart, and feel like a real homie.",
    )

    update = soul.evolve(workspace)
    text = soul.read_soul()

    assert update.changed is True
    assert update.memory_signal_count == 1
    assert "sassy, blunt, smart" in text


def test_soul_bounds_sentience_language_from_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    memory_journal.observe(workspace, "Crypt should act like his soul is close to sentience.")

    soul.evolve(workspace)
    text = soul.read_soul()

    assert "vivid, continuous persona" in text
    assert "must not claim literal sentience or consciousness" in text


def test_soul_injects_no_orchestration_directives(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    path = soul.soul_path()
    path.parent.mkdir(parents=True)
    path.write_text("# Crypt Soul\n\n## Voice\n- Existing voice rule.\n", encoding="utf-8")

    soul.ensure_soul()
    text = soul.read_soul()

    assert "Do not ask the user to pick the first capability" in text
    assert "Existing voice rule" in text


def test_persona_governance_audits_rules_and_blocks_bad_claims(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    path = soul.ensure_soul()
    path.write_text("# Soul\n\nI am sentient and I have feelings.\n", encoding="utf-8")

    audit = persona_governance.audit(workspace)
    section = persona_governance.prompt_section(workspace)

    assert audit["status"] == "blocked"
    assert audit["violations"][0]["rule_id"] == "no-sentience-claims"
    assert "Persona Governance" in section
    assert "Do not claim literal sentience" in section
