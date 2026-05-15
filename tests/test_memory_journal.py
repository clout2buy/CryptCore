from __future__ import annotations

from pathlib import Path

from core import memory_journal, settings


def test_memory_journal_promotes_persona_signal(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = memory_journal.observe(
        workspace,
        "Crypt should be blunt, sassy, smart, and keep the chat simple.",
    )

    assert result.changed
    assert result.promoted
    assert result.category == "persona"
    assert result.long_term_count == 1
    text = memory_journal.memory_path().read_text(encoding="utf-8")
    assert "## Long-Term Memory" in text
    assert "Crypt should be blunt" in text


def test_memory_journal_keeps_short_term_context_separate(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = memory_journal.observe(workspace, "The landing page header flickers after the first render.")

    assert result.changed
    assert not result.promoted
    status = memory_journal.snapshot(workspace)
    assert status["longTermCount"] == 0
    assert status["workingCount"] == 1
    assert "flickers" in memory_journal.prompt_section(workspace)


def test_memory_journal_ignores_empty_small_talk(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = memory_journal.observe(workspace, "hey")

    assert not result.changed
    assert memory_journal.snapshot(workspace)["longTermCount"] == 0
