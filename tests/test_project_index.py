from __future__ import annotations

from core import project_index, settings


def test_project_index_detects_repo_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text(
        "[project]\n"
        "name='demo'\n"
        "dependencies=['fastapi>=0.1', 'rich']\n"
        "[project.scripts]\n"
        "demo='demo.__main__:main'\n",
        encoding="utf-8",
    )
    (workspace / "package.json").write_text(
        '{"scripts":{"test":"vitest run","build":"vite build"},"devDependencies":{"vite":"^5","react":"^18"}}',
        encoding="utf-8",
    )
    (workspace / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (workspace / "demo").mkdir()
    (workspace / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (workspace / "demo" / "__main__.py").write_text("def main(): pass\n", encoding="utf-8")
    (workspace / ".github" / "workflows").mkdir(parents=True)
    (workspace / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (workspace / "src" / "more.py").write_text("print('there')\n", encoding="utf-8")

    profile = project_index.refresh(workspace)

    assert "Python" in profile.languages
    assert "JavaScript/TypeScript" in profile.languages
    assert "python" in profile.package_managers
    assert "FastAPI" in profile.frameworks
    assert "Rich TUI" in profile.frameworks
    assert "React" in profile.frameworks
    assert "Vite" in profile.frameworks
    assert "python main.py" in profile.entrypoints
    assert "python -m demo" in profile.entrypoints
    assert "demo -> demo.__main__:main" in profile.entrypoints
    assert ".github\\workflows\\ci.yml" in profile.ci_files or ".github/workflows/ci.yml" in profile.ci_files
    assert "npm run test" in profile.test_commands
    assert "python -m pytest" in profile.test_commands
    assert "npm run build" in profile.build_commands

    cached = project_index.load(workspace)
    assert cached is not None
    assert cached.root == str(workspace.resolve())
    prompt_section = project_index.prompt_section(workspace)
    assert "# Project Intelligence" in prompt_section
    assert "Frameworks/libraries" in prompt_section
    assert "Entry points" in prompt_section


def test_project_index_surfaces_attention_flags(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    profile = project_index.refresh(workspace)

    assert "no automated test command detected" in profile.risk_flags
    assert "no CI workflow detected" in profile.risk_flags
    assert "missing README.md" in profile.risk_flags
    assert "Attention flags" in project_index.prompt_section(workspace)
