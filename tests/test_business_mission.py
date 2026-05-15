from __future__ import annotations

from pathlib import Path

from core import business_entities, business_mission, mission_router, settings, webui, work_threads


def test_business_mission_template_contains_full_launch_tree():
    tasks = business_mission.stage_tasks()
    keys = [task["key"] for task in tasks]

    assert keys == [
        "idea",
        "market",
        "offer",
        "brand",
        "landing",
        "payment",
        "content",
        "operations",
        "analytics",
        "launch",
    ]
    assert any(task["approval_required"] for task in tasks if task["key"] == "payment")
    assert len(business_mission.success_metrics()) == 3


def test_business_request_creates_template_thread(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    decision = mission_router.observe(
        workspace,
        "Start a business selling printable posters, build the landing page, and track revenue weekly.",
    )
    assert decision.goal is not None

    thread = work_threads.ensure_for_goal(decision.goal, prompt_text=decision.goal.description)
    titles = [task["title"] for task in thread.tasks]

    assert len(thread.tasks) == 10
    assert "Prepare payment path" in titles
    assert "Set up analytics and revenue tracking" in titles
    assert thread.blockers
    assert len(thread.success_metrics) >= 3
    assert any("Payment and external launch actions" in metric for metric in thread.success_metrics)


def test_business_template_prompt_context(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    text = webui._prompt_with_context("Start a business and track income weekly", [], workspace=workspace)

    assert "Business Mission Template" in text
    assert "payment: Prepare payment path approval-gated" in text


def test_business_entity_registry_tracks_launch_objects(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    observation = business_entities.observe_text(
        workspace,
        "The business named Atlas Prints has offer called Starter Poster Pack, domain atlasprints.com, "
        "reddit channel, spent $25 on ads, and revenue stream $99 from poster sales.",
    )

    assert observation.changed
    snapshot = business_entities.snapshot(workspace)
    assert snapshot["kindCounts"]["business"] >= 1
    assert snapshot["kindCounts"]["offer"] >= 1
    assert snapshot["kindCounts"]["domain"] >= 1
    assert snapshot["kindCounts"]["expense"] >= 1
    assert snapshot["kindCounts"]["revenue-stream"] >= 1
    assert snapshot["valueTotals"]["expense"] == 25
    assert business_entities.markdown_path(workspace).exists()

    section = business_entities.prompt_section(workspace)
    assert "Business Entity Registry" in section
    assert "Atlas Prints" in section
