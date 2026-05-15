from __future__ import annotations

from core import business_launch, office_layer, revenue_ops, settings, website_pipeline, work_threads


def test_business_launch_autopilot_creates_connected_launch_state(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    launch = business_launch.start(
        workspace,
        "Start a business selling AI website audits to local shops.",
        target_revenue=750,
    )

    assert launch.status == "active"
    assert launch.goal_id
    assert launch.thread_id
    assert launch.pipeline_id
    assert launch.revenue_target_id
    assert launch.office_artifact_id
    assert any(stage.approval_required for stage in launch.stages)
    assert business_launch.snapshot(workspace)["approvalGated"] >= 3
    assert website_pipeline.list_pipelines(workspace)[0].pipeline_id == launch.pipeline_id
    assert revenue_ops.list_targets(workspace)[0].target_revenue == 750
    assert office_layer.list_artifacts(workspace)[0].office_id == launch.office_artifact_id
    thread = work_threads.list_threads(workspace, include_all=True)[0]
    assert thread.artifacts


def test_business_launch_ensure_for_prompt_dedupes(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    text = "Build a business that tracks gym leads and monthly income."

    first = business_launch.ensure_for_prompt(workspace, text)
    second = business_launch.ensure_for_prompt(workspace, text)

    assert first.created is True
    assert second.created is False
    assert first.launch is not None
    assert second.launch is not None
    assert first.launch.launch_id == second.launch.launch_id
    assert "Business Launch Autopilot" in business_launch.prompt_section(workspace)
