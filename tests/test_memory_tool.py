from __future__ import annotations

from pathlib import Path

from tools import registry


def _isolated_memory(monkeypatch, tmp_path: Path) -> Path:
    from core import memory

    memory_dir = tmp_path / "memory"
    memory_index = memory_dir / "MEMORY.md"
    monkeypatch.setattr(memory, "MEMORY_DIR", memory_dir)
    monkeypatch.setattr(memory, "MEMORY_INDEX", memory_index)
    return memory_index


def test_memory_read_alias_lists_memory(monkeypatch, tmp_path):
    memory_index = _isolated_memory(monkeypatch, tmp_path)
    memory_index.parent.mkdir(parents=True)
    memory_index.write_text("# Crypt Memory\n\n## Workflow\n- use focused tests\n", encoding="utf-8")

    ok, output = registry.dispatch("memory", {"action": "read"}, render=False)

    assert ok is True
    assert "use focused tests" in output


def test_memory_show_alias_is_safe(monkeypatch, tmp_path):
    _isolated_memory(monkeypatch, tmp_path)

    ok, output = registry.dispatch("memory", {"action": "show"}, render=False)

    assert ok is True
    assert "# Crypt Memory" in output
