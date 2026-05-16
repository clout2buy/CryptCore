from __future__ import annotations

from pathlib import Path

from core import connector_readiness, credential_vault, integrations, settings


def test_connector_readiness_defaults_to_draft_only_for_missing_auth(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    snap = connector_readiness.snapshot(workspace)
    reddit = next(card for card in snap["cards"] if card["connector_id"] == "reddit")

    assert reddit["status"] == "needs-auth"
    assert "draft posts" in reddit["safe_actions"]
    assert "submit posts" in reddit["approval_actions"]
    assert snap["needsAuth"] >= 1


def test_connector_readiness_uses_configured_integrations_and_credentials(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    integrations.set_integration("reddit", configured=True, enabled=True, notes="oauth ready")
    credential_vault.add_reference(
        workspace,
        service="reddit",
        purpose="post and comment drafts",
        reference="password manager item",
        status="available",
    )

    decision = connector_readiness.assess(workspace, "post this announcement to Reddit")

    assert decision["connector"] == "reddit"
    assert decision["ready"] is True
    assert decision["approvalRequired"] is True
    assert "Draft" in decision["safeNextStep"] or "approval" in decision["safeNextStep"]


def test_connector_readiness_prompt_instructs_safe_external_use(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    text = connector_readiness.prompt_section(workspace, "send an email to a lead")

    assert "Connector Readiness" in text
    assert "Never ask the user to paste raw secrets" in text
    assert "approvalRequired=True" in text
