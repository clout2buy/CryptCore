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
    )

    assert profile.route_role == "builder"
    assert profile.provider == "crypt"
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
