from __future__ import annotations

from pathlib import Path

from core import artifact_studio, goals, local_search_index, settings


def test_local_search_index_collects_docs_missions_artifacts_and_skills(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Rocket Ledger\n\nTrack revenue and launch notes.\n", encoding="utf-8")
    skill_dir = workspace / ".agents" / "skills" / "frontend-design"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: frontend-design\ndescription: Build polished UI systems.\n---\n# Frontend\n",
        encoding="utf-8",
    )
    goals.add_goal(
        "Launch revenue tracker",
        workspace=workspace,
        description="Monitor customer payments and monthly recurring revenue.",
    )
    artifact = workspace / "reports" / "launch.md"
    artifact.parent.mkdir()
    artifact.write_text("# Launch Report\n\nRevenue dashboard artifact.\n", encoding="utf-8")
    artifact_studio.record_artifact(workspace, artifact, provenance="created for revenue mission")

    index = local_search_index.refresh(workspace)

    assert index.sources["doc"] >= 1
    assert index.sources["mission"] >= 1
    assert index.sources["artifact"] >= 1
    assert index.sources["skill"] >= 1
    hits = local_search_index.search(workspace, "revenue dashboard", limit=4)
    assert hits
    assert hits[0].score >= hits[-1].score
    assert any(hit.source in {"artifact", "mission", "doc"} for hit in hits)
    assert "Local Search" in local_search_index.prompt_section(workspace, "revenue dashboard")


def test_local_search_index_snapshot_uses_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "docs").mkdir()
    (workspace / "docs" / "ops.md").write_text("# Ops\n\nBrowser QA and release checks.\n", encoding="utf-8")

    snapshot = local_search_index.snapshot(workspace)

    assert snapshot["documents"] >= 1
    assert snapshot["sources"]["doc"] == 1
    assert Path(snapshot["path"]).exists()
