from __future__ import annotations

from pathlib import Path

from core import release_train, settings


def test_release_train_writes_markdown_and_json(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")

    report = release_train.generate(
        workspace,
        checks=['python -c "print(\'ok\')"'],
        output_root=tmp_path / "releases",
    )

    assert report.success is True
    assert report.version == "9.9.9"
    assert (Path(report.output_dir) / "release-checklist.md").exists()
    assert (Path(report.output_dir) / "release-checklist.json").exists()
    text = (Path(report.output_dir) / "release-checklist.md").read_text(encoding="utf-8")
    assert "## Verification" in text
    assert "## Rollback" in text
    assert "## GitHub Flow" in text
    assert "## Screenshots" in text
    assert "PLANNED desktop" in text
    assert "PLANNED mobile" in text
    assert (Path(report.output_dir) / "screenshot-plan.json").exists()


def test_release_train_blocks_failed_check(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    report = release_train.generate(
        workspace,
        checks=['python -c "raise SystemExit(2)"'],
        output_root=tmp_path / "releases",
    )

    assert report.success is False
    assert any(risk.startswith("BLOCKER:") for risk in report.known_risks)
