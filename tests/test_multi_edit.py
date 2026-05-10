"""multi_edit — atomic across files. Validates the all-or-nothing contract."""
from __future__ import annotations

from pathlib import Path

import pytest

from core import file_state
from tools import multi_edit, registry


def setup_read(p: Path) -> None:
    file_state.record_read(p, p.read_bytes())


def test_two_files_succeed(workspace: Path):
    a = workspace / "a.txt"
    b = workspace / "b.txt"
    a.write_text("alpha\n")
    b.write_text("beta\n")
    setup_read(a)
    setup_read(b)
    out = multi_edit.run({"changes": [
        {"path": str(a), "old": "alpha", "new": "ALPHA"},
        {"path": str(b), "old": "beta", "new": "BETA"},
    ]})
    assert "2 file" in out
    assert a.read_text() == "ALPHA\n"
    assert b.read_text() == "BETA\n"


def test_atomic_abort_no_writes(workspace: Path):
    a = workspace / "a.txt"
    b = workspace / "b.txt"
    a.write_text("alpha\n")
    b.write_text("beta\n")
    setup_read(a)
    setup_read(b)
    with pytest.raises(ValueError, match="aborted"):
        multi_edit.run({"changes": [
            {"path": str(a), "old": "alpha", "new": "ALPHA"},
            {"path": str(b), "old": "MISSING", "new": "x"},
        ]})
    assert a.read_text() == "alpha\n"
    assert b.read_text() == "beta\n"


def test_same_file_multiple_entries_merged(workspace: Path):
    a = workspace / "a.txt"
    a.write_text("x\ny\n")
    setup_read(a)
    multi_edit.run({"changes": [
        {"path": str(a), "old": "x", "new": "X"},
        {"path": str(a), "old": "y", "new": "Y"},
    ]})
    assert a.read_text() == "X\nY\n"


def test_unread_file_blocks_atomically(workspace: Path):
    a = workspace / "a.txt"
    b = workspace / "b.txt"
    a.write_text("alpha\n")
    b.write_text("beta\n")
    setup_read(a)
    # Skip setup_read(b).
    with pytest.raises(ValueError, match="aborted"):
        multi_edit.run({"changes": [
            {"path": str(a), "old": "alpha", "new": "ALPHA"},
            {"path": str(b), "old": "beta", "new": "BETA"},
        ]})
    assert a.read_text() == "alpha\n"
    assert b.read_text() == "beta\n"


def test_write_failure_rolls_back_prior_files(workspace: Path, monkeypatch: pytest.MonkeyPatch):
    a = workspace / "a.txt"
    b = workspace / "b.txt"
    a.write_text("alpha\n")
    b.write_text("beta\n")
    setup_read(a)
    setup_read(b)
    real_atomic_write = multi_edit._atomic_write

    def flaky_atomic_write(path: Path, data: bytes) -> None:
        if path == b:
            raise OSError("simulated disk failure")
        real_atomic_write(path, data)

    monkeypatch.setattr(multi_edit, "_atomic_write", flaky_atomic_write)
    with pytest.raises(RuntimeError, match="rolled back"):
        multi_edit.run({"changes": [
            {"path": str(a), "old": "alpha", "new": "ALPHA"},
            {"path": str(b), "old": "beta", "new": "BETA"},
        ]})

    assert a.read_text() == "alpha\n"
    assert b.read_text() == "beta\n"


def test_preview_returns_combined_diff(workspace: Path):
    a = workspace / "a.txt"
    a.write_text("hi\n")
    setup_read(a)
    out = multi_edit.preview({"changes": [{"path": str(a), "old": "hi", "new": "HI"}]})
    assert "-hi" in out
    assert "+HI" in out


def test_summary_shape():
    s = multi_edit.summary({"changes": [
        {"path": "a.py", "old": "x", "new": "y"},
        {"path": "b.py", "edits": [{"old": "1", "new": "2"}, {"old": "3", "new": "4"}]},
    ]})
    assert "2" in s  # 2 files
    assert "3" in s  # 3 edits


def test_empty_edits_are_rejected_before_approval(workspace: Path):
    a = workspace / "a.txt"
    a.write_text("alpha\n")
    setup_read(a)

    ok, msg = registry.dispatch(
        "multi_edit",
        {"changes": [{"path": str(a), "edits": []}]},
        render=False,
    )

    assert ok is False
    assert "non-empty" in msg
