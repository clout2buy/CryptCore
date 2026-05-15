from __future__ import annotations

from pathlib import Path

from core import agent_delegation, agent_profiles, intent_router, settings, webui


def test_delegation_brain_suggests_and_creates_specialist(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    route = intent_router.route("Start a business, find customers, and track revenue weekly.")

    decision = agent_delegation.decide(workspace, "Start a business, find customers, and track revenue weekly.", route)
    created = agent_delegation.apply_decision(workspace, decision)
    next_decision = agent_delegation.decide(workspace, "Find more customers and track revenue.", route)

    assert decision.action == "create-agent"
    assert decision.agent_name == "Growth Operator"
    assert created is not None
    assert created.tools
    assert next_decision.action == "use-agent"
    assert next_decision.agent_id == created.id


def test_delegation_brain_uses_existing_profile(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    profile = agent_profiles.create_profile(
        workspace,
        name="Research Scout",
        purpose="Search market signals, compare sources, and find customer leads.",
        agent_type="explorer",
        provider="crypt",
        model="crypt-fast",
        routing_hints=["Use for research and customer lead discovery."],
    )

    decision = agent_delegation.decide(workspace, "Research customer lead sources.")

    assert decision.action == "use-agent"
    assert decision.agent_id == profile.id
    assert decision.route_role == "planner"


def test_delegation_brain_keeps_small_talk_local(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()

    decision = agent_delegation.decide(workspace, "hey what are you up to?")

    assert decision.action == "local"


def test_webui_snapshot_and_prompt_include_delegation(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        snapshot = handler_obj._snapshot()
    finally:
        server.server_close()
    prompt = webui._prompt_with_context("Build a customer outreach business", [], workspace=workspace)

    assert "agentDelegation" in snapshot
    assert "Agent Delegation Brain" in prompt
