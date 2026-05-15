from __future__ import annotations

from pathlib import Path

from core import artifact_studio, goals, settings, work_threads
from tools import write_file


def test_artifact_studio_records_mission_preview(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal(
        "Launch tracker",
        description="Build the launch dashboard",
        workspace=workspace,
        success_metric="dashboard exists",
        tags=["artifact"],
    )
    thread = work_threads.ensure_for_goal(goal, prompt_text="Build the launch dashboard")
    artifact = workspace / "site" / "index.html"
    artifact.parent.mkdir()
    artifact.write_text("<html><body>Launch dashboard</body></html>\n", encoding="utf-8")

    record = artifact_studio.record_artifact(
        workspace,
        artifact,
        mission_id=goal.goal_id,
        provenance="write_file",
    )
    snapshot = artifact_studio.snapshot(workspace)
    refreshed = work_threads.list_threads(workspace, include_all=True)[0]

    assert record.kind == "site"
    assert record.mission_id == goal.goal_id
    assert record.thread_id == thread.thread_id
    assert "Launch dashboard" in record.preview
    assert "site\\index.html" in refreshed.artifacts or "site/index.html" in refreshed.artifacts
    assert snapshot["summary"]["missionLinked"] == 1
    assert snapshot["groups"][0]["title"] == "Launch tracker"


def test_write_file_registers_recent_mission_artifact(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    monkeypatch.setenv("CRYPT_ROOT", str(workspace))
    goal = goals.add_goal(
        "Research report",
        description="Write a durable report",
        workspace=workspace,
        success_metric="report saved",
        tags=["artifact"],
    )
    thread = work_threads.ensure_for_goal(goal, prompt_text="Write a durable report")

    output = write_file.run({"path": "report.md", "content": "# Report\n\nFindings.\n"})
    records = artifact_studio.list_artifacts(workspace)

    assert "created report.md" in output
    assert records[0].rel_path == "report.md"
    assert records[0].thread_id == thread.thread_id
    assert "Findings" in records[0].preview
