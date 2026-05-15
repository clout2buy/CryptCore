from __future__ import annotations

from pathlib import Path

from core import code_builder, settings


def test_code_builder_plan_has_required_stage_order(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (workspace / "core").mkdir()
    (workspace / "core" / "app.py").write_text("def ok():\n    return True\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    plan = code_builder.plan_task(workspace, "fix the bug in core/app.py and run tests")

    assert [stage.name for stage in plan.stages] == list(code_builder.STAGE_ORDER)
    assert "core/app.py" in plan.primary_files
    assert any("pytest" in command for command in plan.check_commands)
    assert plan.stages[0].command.startswith("read/search")
    assert plan.stages[-1].command == "git status --short"


def test_code_builder_prompt_section_is_compact(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")

    section = code_builder.prompt_section(workspace, "implement a frontend component")

    assert "Code Builder Loop" in section
    assert "inspect -> plan -> patch -> test -> review -> summarize -> commit-ready" in section
    assert "Likely checks" in section


def test_code_builder_report_marks_commit_ready(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    report = code_builder.report_change(
        workspace,
        changed_files=["core/app.py", "tests/test_app.py"],
        checks=[{"command": "pytest tests/test_app.py", "ok": True}],
    )

    assert report.ready is True
    assert report.next_stage == "commit-ready"
    assert report.checks_passed == 1
    assert "2 changed files" in report.diff_summary
