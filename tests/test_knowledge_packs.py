from __future__ import annotations

from pathlib import Path

from core import asset_library, business_crm, goals, knowledge_packs, research_sources, settings, work_threads


def test_knowledge_pack_builder_writes_portable_markdown(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Launch Notes\n\nBuild the offer.", encoding="utf-8")
    goal = goals.add_goal("Launch offer", workspace=workspace, success_metric="first customer")
    work_threads.ensure_for_goal(goal, prompt_text="launch offer")
    asset_library.record_asset(workspace, workspace / "README.md", purpose="launch notes", provenance="test")
    business_crm.upsert_contact(workspace, name="Jordan", email="jordan@example.com", next_action="draft email")
    research_sources.add_source(workspace, url="https://example.com/source", title="Source")

    manifest = knowledge_packs.build_pack(workspace, title="Launch Pack", query="launch offer")
    text = Path(manifest.path).read_text(encoding="utf-8")
    snapshot = knowledge_packs.snapshot(workspace)

    assert manifest.item_count >= 1
    assert "# Launch Pack" in text
    assert "Reusable Assets" in text
    assert "CRM Snapshot" in text
    assert "Research Sources" in text
    assert snapshot["total"] == 1
    assert "Knowledge Packs" in knowledge_packs.prompt_section(workspace)


def test_knowledge_pack_snapshot_empty(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    snapshot = knowledge_packs.snapshot(workspace)

    assert snapshot["total"] == 0
    assert snapshot["latest"] is None
