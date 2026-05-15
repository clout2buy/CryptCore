from __future__ import annotations

from pathlib import Path

from core import evidence, settings, tool_capability_cards


def test_tool_capability_cards_include_risk_examples_and_usage(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    evidence.clear()
    try:
        evidence.record_tool_result(
            "read_file",
            {"path": "README.md"},
            ok=True,
            output="read ok",
            task_id="task-tools",
        )

        data = tool_capability_cards.snapshot(limit=120)
        cards = {card["name"]: card for card in data["cards"]}

        assert data["total"] >= 10
        assert data["used"] >= 1
        assert "read_file" in cards
        assert cards["read_file"]["scope"] == "filesystem-read"
        assert cards["read_file"]["risk"] == "low"
        assert cards["read_file"]["examples"]
        assert cards["read_file"]["permissionNeeds"]
        assert cards["read_file"]["recoveryHints"]
        assert cards["read_file"]["usage"]["total"] == 1
        assert cards["read_file"]["usage"]["successes"] == 1
    finally:
        evidence.clear()


def test_tool_capability_prompt_section_mentions_loaded_tools(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    evidence.clear()

    section = tool_capability_cards.prompt_section(limit=3)

    assert "# Tool Capability Cards" in section
    assert "tool(s) loaded" in section
