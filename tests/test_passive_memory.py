from __future__ import annotations

from pathlib import Path

from core import learning, passive_memory, settings, soul


def test_passive_memory_ignores_small_talk(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = passive_memory.observe(workspace, "hey")

    assert not result.learned
    assert learning.list_lessons(workspace) == []


def test_passive_memory_captures_persona_feedback(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = passive_memory.observe(workspace, "Crypt should be blunt, sassy, smart, and not talk like a robot.")

    assert result.learned
    assert result.category == "persona"
    assert result.confidence >= 0.8
    assert {"passive", "persona", "preference"} <= set(result.tags)
    assert learning.list_lessons(workspace)[0].text.startswith("Crypt should")
    assert "blunt" in soul.read_soul()


def test_passive_memory_captures_project_facts(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = passive_memory.observe(workspace, "The launch tracker folder is saved at D:/CryptCore/Launch Ops.")

    assert result.learned
    assert result.category == "project"
    assert {"passive", "project"} <= set(result.tags)
    assert learning.list_lessons(workspace)[0].text.startswith("Project fact:")


def test_passive_memory_captures_tool_quirks(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = passive_memory.observe(workspace, "Whenever the mic toggle fails, retry voice capture before sending.")

    assert result.learned
    assert result.category == "tool"
    assert {"tool", "recurring"} <= set(result.tags)
    assert "Tool or workflow lesson:" in learning.list_lessons(workspace)[0].text


def test_passive_memory_drops_short_questions():
    decision = passive_memory.decide("what are we doing?")

    assert not decision.capture
    assert "question" in decision.reason
