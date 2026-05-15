from __future__ import annotations

from pathlib import Path

from core import memory_condenser, memory_journal, settings


def test_memory_condenser_promotes_typed_working_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    memory_journal.observe(workspace, "The repo path is D:/CryptCore.")

    result = memory_condenser.condense(workspace, now=10)
    snapshot = memory_journal.snapshot(workspace)

    assert result.promoted == 1
    assert snapshot["longTermCount"] == 1
    assert snapshot["workingCount"] == 0
    assert memory_journal.filter_signals(workspace, memory_type="project-fact")[0]["decay"] == "stable"


def test_memory_condenser_discards_stale_low_confidence_working_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    memory_journal.observe(workspace, "The landing page header flickers after the first render.")
    state = memory_journal._read_state()  # noqa: SLF001 - migration fixture
    state["working"][0]["updated_at"] = 1
    state["working"][0]["created_at"] = 1
    memory_journal._write_state(state)  # noqa: SLF001

    result = memory_condenser.condense(workspace, now=memory_condenser.STALE_SECONDS + 20)

    assert result.discarded == 1
    assert memory_journal.snapshot(workspace)["workingCount"] == 0


def test_memory_condenser_merges_duplicate_working_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    memory_journal.observe(workspace, "The landing page header flickers after first render.")
    state = memory_journal._read_state()  # noqa: SLF001 - migration fixture
    duplicate = dict(state["working"][0])
    duplicate["updated_at"] += 1
    state["working"].append(duplicate)
    memory_journal._write_state(state)  # noqa: SLF001

    result = memory_condenser.condense(workspace)
    signals = memory_journal.filter_signals(workspace)

    assert result.merged == 1
    assert len(signals) == 1
    assert signals[0]["hits"] >= 2
