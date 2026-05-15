from __future__ import annotations

from pathlib import Path

from core import memory_importance, memory_journal, settings


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


def test_memory_journal_stores_type_confidence_and_sensitivity(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    memory_journal.observe(workspace, "My email is test@example.com for launch follow ups.")
    status = memory_journal.snapshot(workspace)
    signals = memory_journal.filter_signals(workspace, memory_type="business", min_confidence=0.8)

    assert status["typeCounts"]["business"] == 1
    assert signals[0]["sensitivity"] == "private"
    assert signals[0]["confidence"] >= 0.8
    assert memory_journal.filter_signals(workspace, include_sensitive=False) == []


def test_memory_journal_records_correction_history(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    memory_journal.observe(workspace, "The repo path is D:/CryptCore.")
    memory_journal.observe(workspace, "Actually the repo path is D:/CryptCore.")
    signal = memory_journal.filter_signals(workspace, memory_type="project-fact")[0]

    assert signal["corrections"]
    assert signal["memory_type"] == "project-fact"
    assert signal["decay"] == "working"


def test_memory_importance_scores_preference_project_risk_and_future_use():
    score = memory_importance.score_text(
        "Crypt should always track revenue emails and follow up every week.",
        category="business",
        previous_hits=2,
    )

    assert score.promote
    assert score.preference > 0
    assert score.project_value > 0
    assert score.risk > 0
    assert score.future_usefulness > 0
    assert score.recurrence > 0


def test_memory_journal_saves_importance_breakdown(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    memory_journal.observe(workspace, "My launch email is test@example.com and should be used for weekly customer follow ups.")
    signal = memory_journal.filter_signals(workspace, memory_type="recurring", min_confidence=0.8)[0]

    assert signal["importance"]["risk"] > 0
    assert signal["importance"]["future_usefulness"] > 0
