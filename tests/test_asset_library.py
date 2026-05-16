from __future__ import annotations

from pathlib import Path

from core import artifact_studio, asset_library, settings


def test_asset_library_indexes_workspace_assets(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "site.html").write_text("<main>Crypt</main>", encoding="utf-8")
    (workspace / "notes.md").write_text("# Notes", encoding="utf-8")
    (workspace / "hero.png").write_bytes(b"\x89PNG\r\n")

    indexed = asset_library.index_workspace(workspace)
    snapshot = asset_library.snapshot(workspace)

    assert len(indexed) == 3
    assert snapshot["total"] == 3
    assert snapshot["byKind"]["ui"] == 1
    assert snapshot["byKind"]["image"] == 1
    assert snapshot["reusable"] == 3
    assert "Asset Library" in asset_library.prompt_section(workspace)


def test_asset_library_includes_artifact_studio_records(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    output = workspace / "build" / "landing.html"
    output.parent.mkdir()
    output.write_text("<h1>Offer</h1>", encoding="utf-8")
    artifact_studio.record_artifact(workspace, output, kind="site", provenance="website pipeline")

    snapshot = asset_library.snapshot(workspace)

    assert snapshot["total"] == 1
    assert snapshot["assets"][0]["source"] == "artifact-studio"
    assert "website pipeline" in snapshot["assets"][0]["provenance"]
