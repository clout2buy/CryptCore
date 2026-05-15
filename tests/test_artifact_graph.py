from __future__ import annotations

from pathlib import Path

from core import agent_profiles, artifact_graph, artifact_studio, evidence, goals, learning, settings, work_threads


def test_artifact_graph_links_missions_threads_artifacts_and_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    evidence.clear()
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal("Launch dashboard", workspace=workspace, success_metric="site exists")
    thread = work_threads.ensure_for_goal(goal, prompt_text="Build the launch dashboard")
    artifact = workspace / "site" / "index.html"
    artifact.parent.mkdir()
    artifact.write_text("<html>launch</html>", encoding="utf-8")
    record = artifact_studio.record_artifact(workspace, artifact, mission_id=goal.goal_id, status="verified")
    learning.add_lesson(
        "When updating site/index.html, run the browser smoke check.",
        cwd=workspace,
        tags=["artifact", "verification"],
    )

    graph = artifact_graph.build(workspace)
    edges = {(edge["source"], edge["target"], edge["kind"]) for edge in graph["edges"]}

    assert graph["summary"]["artifacts"] == 1
    assert graph["summary"]["missions"] == 1
    assert (f"goal:{goal.goal_id}", f"thread:{thread.thread_id}", "owns") in edges
    assert (f"thread:{thread.thread_id}", f"artifact:{record.artifact_id}", "produced") in edges
    assert any(edge[2] == "informs" and edge[1] == f"artifact:{record.artifact_id}" for edge in edges)
    assert any(edge[2] == "verified" and edge[1] == f"artifact:{record.artifact_id}" for edge in edges)


def test_artifact_graph_includes_agent_and_prompt_section(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    agent_profiles.create_profile(
        workspace,
        name="Frontend Builder",
        purpose="Build polished interfaces",
        agent_type="worker",
        provider="crypt",
        model="crypt-pro",
    )

    graph = artifact_graph.build(workspace)
    section = artifact_graph.prompt_section(workspace)

    assert graph["summary"]["agents"] == 1
    assert "# Artifact Dependency Graph" in section
