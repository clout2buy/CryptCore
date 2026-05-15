from __future__ import annotations

import pytest

from core import credential_vault, settings


def test_credential_vault_tracks_references_without_raw_secrets(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    ref = credential_vault.add_reference(
        workspace,
        service="Stripe",
        purpose="payment checkout setup",
        account_hint="owner dashboard",
        reference="env:STRIPE_SECRET_KEY",
        status="available",
    )

    assert ref.status == "available"
    assert ref.reference == "env:STRIPE_SECRET_KEY"
    snap = credential_vault.snapshot(workspace)
    assert snap["total"] == 1
    assert snap["available"] == 1
    assert "Credential References" in credential_vault.prompt_section(workspace)


def test_credential_vault_rejects_raw_secret_values(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    with pytest.raises(ValueError, match="refused"):
        credential_vault.add_reference(
            workspace,
            service="OpenAI",
            purpose="model access",
            reference="sk-1234567890abcdefghijklmnopqrstuvwxyz",
        )


def test_credential_vault_observes_needed_accounts(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    ref = credential_vault.observe_need(workspace, "We need a Reddit login before posting launch drafts.")

    assert ref is not None
    assert ref.service == "reddit"
    assert credential_vault.snapshot(workspace)["needed"] == 1
