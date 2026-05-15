from __future__ import annotations

from pathlib import Path

import pytest

from core import integrations, settings, webui


def test_integrations_are_disabled_by_default(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")

    cards = integrations.list_integrations()

    assert {card.integration_id for card in cards} >= {"github", "email", "calendar", "reddit", "stripe", "analytics"}
    assert all(card.enabled is False for card in cards)
    assert all(card.approval_required for card in cards)
    assert any("post requires approval" in scope for card in cards if card.integration_id == "reddit" for scope in card.scopes)


def test_integration_enable_requires_configuration(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")

    state = integrations.set_integration("stripe", enabled=True)
    configured = integrations.set_integration("stripe", configured=True, enabled=True, notes="test mode")
    card = next(card for card in integrations.list_integrations() if card.integration_id == "stripe")

    assert state.enabled is False
    assert state.status == "needs-setup"
    assert configured.enabled is True
    assert card.status == "enabled"
    assert card.notes == "test mode"


def test_integration_scope_summary_and_webui_snapshot(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    summary = integrations.scope_summary()
    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        snapshot = handler_obj._snapshot()
    finally:
        server.server_close()

    assert "GitHub" in summary
    assert "send requires approval" in summary
    assert "integrationsPreview" in snapshot
    assert snapshot["integrationsPreview"][0]["enabled"] is False


def test_unknown_integration_rejected(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")

    with pytest.raises(KeyError):
        integrations.set_integration("unknown", configured=True)
