from __future__ import annotations

from pathlib import Path

from core import entities, settings, webui


def test_observe_text_extracts_typed_entities(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = entities.observe_text(
        workspace,
        "My email is boss@example.com. The business named Atlas Prints has a reddit channel r/AtlasPrints, "
        "and my client Jordan Lee is the contact.",
    )
    records = entities.list_entities(workspace, limit=20)
    by_kind = {record.kind for record in records}

    assert result.changed is True
    assert {"account", "business", "channel", "person", "relationship"} <= by_kind
    assert any(record.name == "boss@example.com" and record.sensitivity == "private" for record in records)
    assert any(record.name == "Atlas Prints" for record in records)
    assert any(record.name == "r/AtlasPrints" for record in records)
    assert any("Jordan Lee" in record.name for record in records)


def test_entities_dedupe_aliases_and_retrieve_by_query(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    first, changed_first = entities.upsert_entity(
        workspace,
        "business",
        "Night Market Studio",
        aliases=["NMS"],
        details={"platform": "shop"},
        tags=["launch"],
    )
    second, changed_second = entities.upsert_entity(
        workspace,
        "business",
        "Night Market Studio",
        aliases=["night market"],
        details={"url": "https://example.com"},
        tags=["customer"],
    )
    matches = entities.list_entities(workspace, kind="business", query="night market")

    assert changed_first is True
    assert changed_second is True
    assert first.entity_id == second.entity_id
    assert matches[0].mentions == 2
    assert {"NMS", "night market"} <= set(matches[0].aliases)
    assert matches[0].details["url"] == "https://example.com"


def test_entity_prompt_section_keeps_private_accounts_out(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    entities.observe_text(workspace, "My email is private@example.com and the brand called Rocket Ledger is important.")
    section = entities.prompt_section(workspace)

    assert "Contact And Account Memory" in section
    assert "Rocket Ledger" in section
    assert "private@example.com" not in section


def test_webui_snapshot_and_prompt_include_entities(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    entities.observe_text(workspace, "The business named Orbit Desk is the launch company.")

    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        snapshot = handler_obj._snapshot()
    finally:
        server.server_close()
    prompt = webui._prompt_with_context("help with Orbit Desk", [], workspace=workspace)

    assert snapshot["entitiesPreview"]["count"] >= 1
    assert snapshot["entitiesPreview"]["preview"][0]["name"] == "Orbit Desk"
    assert "Contact And Account Memory" in prompt
