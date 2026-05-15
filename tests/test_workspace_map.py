from __future__ import annotations

from pathlib import Path

from core import settings, workspace_map


def test_workspace_map_classifies_safe_generated_and_ignored_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "core").mkdir()
    (workspace / "tests").mkdir()
    (workspace / "docs").mkdir()
    (workspace / "build").mkdir()
    (workspace / ".crypt").mkdir()
    (workspace / ".env").write_text("SECRET=value\n", encoding="utf-8")
    (workspace / ".gitignore").write_text(".env\nbuild/\n", encoding="utf-8")

    data = workspace_map.build(workspace)
    safe = {zone["relPath"] for zone in data["safeZones"] if zone["exists"]}
    generated = {zone["relPath"] for zone in data["generatedZones"] if zone["exists"]}
    risky = {zone["rel_path"] for zone in data["riskyZones"]}
    top = {entry["rel_path"]: entry for entry in data["topLevel"]}

    assert {"core", "tests", "docs"}.issubset(safe)
    assert {"build", ".crypt"}.issubset(generated)
    assert ".env" in risky
    assert top["core"]["safe_to_edit"] is True
    assert top["build"]["generated"] is True
    assert top[".env"]["safe_to_edit"] is False


def test_workspace_map_prompt_section_names_edit_boundaries(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "core").mkdir()
    (workspace / ".env").write_text("SECRET=value\n", encoding="utf-8")

    section = workspace_map.prompt_section(workspace)

    assert "# Workspace Map" in section
    assert "safe edit zones: core" in section
    assert "avoid editing or committing" in section
