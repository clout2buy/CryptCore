from __future__ import annotations

from pathlib import Path

from core import artifact_studio, settings, website_pipeline


def test_website_pipeline_creates_repeatable_site_workflow(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    decision = website_pipeline.ensure_for_prompt(
        workspace,
        "Build a responsive animated landing page for a revenue tracker.",
    )

    assert decision.created
    assert decision.pipeline is not None
    assert {"motion", "responsive", "conversion"} <= set(decision.pipeline.requirements)
    assert [stage.key for stage in decision.pipeline.stages] == [
        "brief",
        "direction",
        "build",
        "preview",
        "qa",
        "iterate",
        "release",
    ]

    matched = website_pipeline.ensure_for_prompt(
        workspace,
        "Build a responsive animated landing page for a revenue tracker.",
    )
    assert not matched.created
    assert matched.pipeline.pipeline_id == decision.pipeline.pipeline_id


def test_website_pipeline_tracks_artifacts_and_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    site = workspace / "launch" / "index.html"
    site.parent.mkdir()
    site.write_text("<!doctype html><html><body>Launch</body></html>\n", encoding="utf-8")

    pipeline = website_pipeline.create_pipeline(workspace, "Make a launch site", title="Launch Site")
    updated = website_pipeline.attach_artifact(workspace, pipeline.pipeline_id, site)
    website_pipeline.update_stage(
        workspace,
        pipeline.pipeline_id,
        "qa",
        status="done",
        output="Desktop and mobile smoke checked.",
        checks=["browser smoke"],
    )

    assert updated.artifacts == ["launch/index.html"]
    assert artifact_studio.snapshot(workspace)["summary"]["total"] == 1
    section = website_pipeline.prompt_section(workspace)
    assert "Website Generator Pipeline" in section
    assert "Launch Site" in section
