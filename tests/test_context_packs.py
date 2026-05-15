from __future__ import annotations

from pathlib import Path

from core import context_packs, entities, goals, memory_journal, settings, webui, work_threads


def test_context_pack_collects_ranked_runtime_context(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "orbit_notes.md").write_text("Orbit Desk launch notes", encoding="utf-8")
    goal = goals.add_goal("Build Orbit Desk customer dashboard", workspace=workspace, success_metric="Dashboard works.")
    work_threads.ensure_for_goal(goal, prompt_text="Build Orbit Desk customer dashboard")
    entities.observe_text(workspace, "The business named Orbit Desk is the customer dashboard project.")
    memory_journal.observe(workspace, "Orbit Desk should keep the customer dashboard simple and visual.")

    pack = context_packs.build(workspace, "Orbit Desk customer dashboard", budget_tokens=900)
    sections = {item.section for item in pack.items}
    labels = {item.title for item in pack.items}

    assert pack.text.startswith("# Crypt Context Pack")
    assert pack.estimated_tokens <= pack.budget_tokens
    assert "Mission State" in sections
    assert "Knowledge Graph" in sections
    assert "Memory" in sections
    assert "Entities" in sections
    assert "Build Orbit Desk customer dashboard" in labels
    assert "Orbit Desk" in labels


def test_context_pack_respects_budget_and_private_entity_boundary(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    for index in range(15):
        goals.add_goal(f"Long running launch task {index}", workspace=workspace, description="Keep this short.")
    entities.observe_text(workspace, "My email is private@example.com and the brand called Public Brand matters.")

    pack = context_packs.build(workspace, "Public Brand launch", budget_tokens=220)

    assert pack.estimated_tokens <= 220
    assert pack.omitted > 0
    assert "Public Brand" in pack.text
    assert "private@example.com" not in pack.text


def test_webui_snapshot_and_prompt_include_context_pack(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goals.add_goal("Track customer replies", workspace=workspace)

    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        snapshot = handler_obj._snapshot()
    finally:
        server.server_close()
    prompt = webui._prompt_with_context("track customer replies", [], workspace=workspace)

    assert snapshot["contextPackPreview"]["budgetTokens"] == 600
    assert snapshot["contextPackPreview"]["items"]
    assert "Crypt Context Pack" in prompt
