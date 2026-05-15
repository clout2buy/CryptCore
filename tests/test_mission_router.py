from __future__ import annotations

from pathlib import Path

from core import goals, mission_router, settings


def test_mission_router_ignores_small_talk(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = mission_router.observe(workspace, "hey")

    assert not result.created
    assert result.goal is None
    assert goals.list_goals(workspace, include_all=True) == []


def test_mission_router_creates_business_mission(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = mission_router.observe(
        workspace,
        "Start a business selling prints, build the site, and track income weekly.",
    )

    assert result.created
    assert result.goal is not None
    assert result.goal.priority == 4
    assert result.goal.cadence == "weekly"
    assert {"auto", "mission", "business", "build", "monitor"} <= set(result.goal.tags)
    assert "business" in result.goal.title.lower()
    assert "Crypt runtime" not in result.prompt_hint
    assert goals.list_goals(workspace)[0].goal_id == result.goal.goal_id


def test_mission_router_reuses_matching_mission(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    first = mission_router.observe(workspace, "Monitor sales revenue for the site every week.")
    second = mission_router.observe(workspace, "Keep tracking sales revenue for the site weekly.")

    assert first.created
    assert not second.created
    assert second.duplicate
    assert second.goal is not None
    assert second.goal.goal_id == first.goal.goal_id
    assert len(goals.list_goals(workspace, include_all=True)) == 1


def test_mission_router_uses_durable_intent_route(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    route = mission_router.intent_router.route("post this to reddit when it is ready")

    result = mission_router.observe(workspace, "post this to reddit when it is ready", route=route)

    assert result.created
    assert result.goal is not None
    assert "external_action" in result.goal.tags
    assert result.goal.priority == 3
