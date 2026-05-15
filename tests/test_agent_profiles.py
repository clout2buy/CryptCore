from __future__ import annotations

import json
from pathlib import Path

from core import agent_profiles, settings


def test_agent_profiles_persist_to_workspace(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    profile = agent_profiles.create_profile(
        workspace,
        name="Growth Operator",
        purpose="Find customers, write launch copy, and track revenue.",
        agent_type="worker",
        provider="crypt",
        model="crypt-pro",
        tools=["web_fetch", "write_file"],
        memory_scope="project",
        persona_constraints=["Blunt and concise"],
        routing_hints=["Use for launch operations"],
    )

    assert profile.route_role == "builder"
    assert profile.provider == "crypt"
    assert profile.tools == ["web_fetch", "write_file"]
    assert profile.memory_scope == "project"
    assert profile.persona_constraints == ["Blunt and concise"]
    assert agent_profiles.store_path(workspace).exists()
    assert json.loads(agent_profiles.store_path(workspace).read_text(encoding="utf-8"))[0]["name"] == "Growth Operator"
    assert agent_profiles.get_profile(workspace, profile.id) == profile


def test_agent_profiles_sanitize_invalid_values(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()

    profile = agent_profiles.create_profile(
        workspace,
        name="",
        purpose="",
        agent_type="nope",
        provider="bad",
        model="",
    )

    assert profile.name == "Crypt Agent"
    assert profile.agent_type == "worker"
    assert profile.provider in settings.PROVIDERS
    assert profile.model
    assert profile.memory_scope == "workspace"


def test_agent_profiles_update_and_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    profile = agent_profiles.create_profile(
        workspace,
        name="Research Scout",
        purpose="Find market signals.",
        agent_type="explorer",
        provider="crypt",
        model="crypt-fast",
    )

    updated = agent_profiles.update_profile(
        workspace,
        profile.id,
        agent_type="worker",
        tools=["web_search", "read_file"],
        memory_scope="session",
        persona_constraints=["No fluff"],
        routing_hints=["Use for customer research"],
    )
    section = agent_profiles.prompt_section(workspace)
    prompt = agent_profiles.profile_prompt(updated)

    assert updated.route_role == "builder"
    assert updated.tools == ["web_search", "read_file"]
    assert updated.memory_scope == "session"
    assert "Saved Agent Profiles" in section
    assert "No fluff" in prompt
