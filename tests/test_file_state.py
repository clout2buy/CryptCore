"""Read-before-edit invariant.

Locks down the contract that edit_file/write_file rely on for safety:
no edits to files Crypt hasn't read in this session, and stale-file
detection that survives mtime-only churn from formatters.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import file_state


def test_unread_file_rejected(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_text("hi")
    with pytest.raises(PermissionError):
        file_state.assert_fresh_for_edit(p)


def test_read_then_edit_allowed(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_text("hi")
    file_state.record_read(p, p.read_bytes())
    file_state.assert_fresh_for_edit(p)  # no raise


def test_external_change_rejected(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_text("hi")
    file_state.record_read(p, p.read_bytes())
    p.write_text("bye")
    with pytest.raises(RuntimeError, match="changed since"):
        file_state.assert_fresh_for_edit(p)


def test_mtime_only_change_tolerated(tmp_path: Path):
    """Formatters often touch mtime without changing content. Crypt should
    detect identical bytes via SHA and let the edit proceed."""
    p = tmp_path / "x.txt"
    data = b"hello"
    p.write_text("hello")
    file_state.record_read(p, data)
    # Force a stat change with same content.
    import os
    new_mtime = p.stat().st_mtime + 10
    os.utime(p, (new_mtime, new_mtime))
    file_state.assert_fresh_for_edit(p)


def test_partial_read_rejected(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_text("hi")
    file_state.record_read(p, b"hi", offset=0, limit=10, partial=True)
    with pytest.raises(PermissionError, match="partial"):
        file_state.assert_fresh_for_edit(p)


def test_missing_file_no_op(tmp_path: Path):
    """assert_fresh_for_edit on a path that doesn't exist must NOT raise —
    write_file uses it for new-file paths."""
    file_state.assert_fresh_for_edit(tmp_path / "nope.txt")


def test_snapshot_restore_round_trip(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_text("a")
    file_state.record_read(p, b"a")
    snap = file_state.snapshot()
    file_state.clear()
    with pytest.raises(PermissionError):
        file_state.assert_fresh_for_edit(p)
    file_state.restore(snap)
    file_state.assert_fresh_for_edit(p)
