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
    assert {"passive", "persona", "preference"} <= set(result.tags)
    assert learning.list_lessons(workspace)[0].text.startswith("Crypt should")
    assert "blunt" in soul.read_soul()
