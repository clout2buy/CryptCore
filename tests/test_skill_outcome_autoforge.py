from __future__ import annotations

from pathlib import Path

from core import learning, settings, skill_outcome_autoforge, skills


def test_outcome_autoforge_finds_repeated_success_patterns(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    learning.add_lesson(
        "Frontend workflow: verify responsive UI with node --check and a browser smoke pass.",
        cwd=workspace,
        tags=["frontend-workflow", "verification"],
        confidence=0.78,
    )
    learning.record_task_outcome(
        cwd=workspace,
        task_id="task-ui-1",
        prompt="Improve the frontend UI and chat layout",
        status="completed",
        final_text="Updated the UI and verified it.",
    )
    learning.record_task_outcome(
        cwd=workspace,
        task_id="task-ui-2",
        prompt="Fix webui styling and frontend input controls",
        status="completed",
        final_text="Polished the frontend.",
    )

    candidates = skill_outcome_autoforge.find_candidates(workspace, min_episodes=2)

    assert candidates
    assert candidates[0].topic == "frontend-workflow"
    assert candidates[0].episode_count == 2
    assert candidates[0].lesson_count >= 1
    assert candidates[0].confidence >= 0.5


def test_outcome_autoforge_creates_discoverable_skill(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    learning.add_lesson(
        "Release workflow: run scripts/verify_core.ps1 -Quick before pushing.",
        cwd=workspace,
        tags=["release-workflow", "verification"],
        confidence=0.82,
    )
    learning.add_lesson(
        "Release workflow: stage only intended files and leave unrelated files alone.",
        cwd=workspace,
        tags=["release-workflow", "git"],
        confidence=0.8,
    )
    for index in range(2):
        learning.record_task_outcome(
            cwd=workspace,
            task_id=f"task-release-{index}",
            prompt="Run release checklist, verify, commit, and push",
            status="completed",
            final_text="Release checks passed.",
        )

    result = skill_outcome_autoforge.autoforge(
        workspace,
        min_episodes=2,
        min_lessons=2,
        force=True,
        max_skills=1,
    )

    assert result.forged[0]["skill"] == "release-workflow"
    assert result.forged[0]["validated"] is True
    assert (workspace / ".crypt" / "skills" / "release-workflow" / "SKILL.md").exists()
    assert "release-workflow" in {skill.name for skill in skills.discover(workspace)}


def test_outcome_autoforge_snapshot_does_not_write_skill(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    for index in range(2):
        learning.record_task_outcome(
            cwd=workspace,
            task_id=f"task-research-{index}",
            prompt="Research sources and cite findings",
            status="completed",
            final_text="Research completed.",
        )

    data = skill_outcome_autoforge.snapshot(workspace)

    assert data["candidates"][0]["topic"] == "research-workflow"
    assert data["forged"] == []
    assert not (workspace / ".crypt" / "skills" / "research-workflow" / "SKILL.md").exists()
