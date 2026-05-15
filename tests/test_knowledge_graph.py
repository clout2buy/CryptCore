from __future__ import annotations

from pathlib import Path

from core import artifact_studio, entities, goals, knowledge_graph, memory_journal, settings, webui, work_threads


def test_graph_links_missions_entities_memory_and_artifacts(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    artifact_path = workspace / "orbit_plan.md"
    artifact_path.write_text("# Orbit Desk\n\nRevenue tracker plan.", encoding="utf-8")

    goal = goals.add_goal(
        "Launch Orbit Desk revenue tracker",
        workspace=workspace,
        success_metric="Revenue dashboard is live.",
        tags=["business"],
    )
    thread = work_threads.ensure_for_goal(goal, prompt_text="Build Orbit Desk tracker")
    entities.observe_text(workspace, "The business named Orbit Desk is the launch company.")
    memory_journal.observe(workspace, "Orbit Desk revenue tracker should stay simple and visual.")
    artifact = artifact_studio.record_artifact(
        workspace,
        artifact_path,
        mission_id=goal.goal_id,
        thread_id=thread.thread_id,
        provenance="test fixture",
    )

    graph = knowledge_graph.build_graph(workspace)
    ids = {node.node_id for node in graph.nodes}
    edges = {(edge.source, edge.target, edge.relation) for edge in graph.edges}

    assert f"goal:{goal.goal_id}" in ids
    assert f"thread:{thread.thread_id}" in ids
    assert f"artifact:{artifact.artifact_id}" in ids
    assert any(node.kind == "entity" and node.label == "Orbit Desk" for node in graph.nodes)
    assert (f"thread:{thread.thread_id}", f"goal:{goal.goal_id}", "owns-goal") in edges
    assert (f"artifact:{artifact.artifact_id}", f"thread:{thread.thread_id}", "attached-to-thread") in edges


def test_graph_query_returns_scoped_context(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goals.add_goal("Build Rocket Ledger customer list", workspace=workspace, tags=["business"])
    entities.observe_text(workspace, "The business named Rocket Ledger is the customer list project.")

    result = knowledge_graph.query(workspace, "Rocket Ledger customer context")
    section = knowledge_graph.prompt_section(workspace, text="Rocket Ledger customer context")
    labels = {node.label for node in result.nodes}

    assert "Build Rocket Ledger customer list" in labels
    assert "Rocket Ledger" in labels
    assert "Knowledge Graph Context" in section
    assert "Rocket Ledger" in section


def test_webui_snapshot_includes_knowledge_graph(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goals.add_goal("Monitor customer inbox", workspace=workspace)

    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        snapshot = handler_obj._snapshot()
    finally:
        server.server_close()

    assert snapshot["knowledgeGraph"]["nodeCount"] >= 1
    assert "goal" in snapshot["knowledgeGraph"]["kindCounts"]
