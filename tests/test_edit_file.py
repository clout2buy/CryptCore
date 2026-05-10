"""edit_file — exact-match replacement, atomic batch, no-match hints,
ambiguous-match diagnostics, line-ending preservation."""
from __future__ import annotations

from pathlib import Path

import pytest

from core import file_state
from tools import edit_file, registry


def setup_read(p: Path) -> None:
    file_state.record_read(p, p.read_bytes())


def test_simple_replace(workspace: Path):
    p = workspace / "x.py"
    p.write_text("alpha\nbeta\n")
    setup_read(p)
    out = edit_file.run({"path": str(p), "old": "alpha", "new": "ALPHA"})
    assert "edited" in out
    assert p.read_text() == "ALPHA\nbeta\n"


def test_no_match_raises_with_hint(workspace: Path):
    p = workspace / "x.py"
    p.write_text("alpha\n")
    setup_read(p)
    with pytest.raises(ValueError, match="no match"):
        edit_file.run({"path": str(p), "old": "GAMMA", "new": "x"})


def test_ambiguous_match_raises_with_line_numbers(workspace: Path):
    p = workspace / "x.py"
    p.write_text("dup\nother\ndup\n")
    setup_read(p)
    with pytest.raises(ValueError, match="2 matches"):
        edit_file.run({"path": str(p), "old": "dup", "new": "X"})


def test_atomic_batch(workspace: Path):
    p = workspace / "x.py"
    p.write_text("one\ntwo\nthree\n")
    setup_read(p)
    out = edit_file.run({"path": str(p), "edits": [
        {"old": "one", "new": "ONE"},
        {"old": "two", "new": "TWO"},
    ]})
    assert "2 edit" in out
    assert p.read_text() == "ONE\nTWO\nthree\n"


def test_atomic_batch_aborts_on_bad_edit(workspace: Path):
    """If edit #2 fails, edit #1 must NOT have been written. The current
    impl applies in-memory then writes at the end, so this is naturally
    atomic — this test guards that."""
    p = workspace / "x.py"
    p.write_text("one\ntwo\n")
    setup_read(p)
    with pytest.raises(ValueError):
        edit_file.run({"path": str(p), "edits": [
            {"old": "one", "new": "ONE"},
            {"old": "GHOST", "new": "x"},
        ]})
    assert p.read_text() == "one\ntwo\n"


def test_unread_file_blocked(workspace: Path):
    p = workspace / "x.py"
    p.write_text("hi\n")
    # Skip setup_read.
    with pytest.raises(PermissionError):
        edit_file.run({"path": str(p), "old": "hi", "new": "bye"})


def test_crlf_preserved(workspace: Path):
    p = workspace / "x.py"
    p.write_bytes(b"alpha\r\nbeta\r\n")
    setup_read(p)
    edit_file.run({"path": str(p), "old": "alpha", "new": "ALPHA"})
    assert p.read_bytes() == b"ALPHA\r\nbeta\r\n"


def test_curly_quote_match_normalisation(workspace: Path):
    """Models often emit ASCII quotes when the file uses curly. The match
    must still succeed (curly/ASCII collapse to the same key during search)
    so the model isn't blocked by quote style. The replacement uses the
    model's text as-is — that's intentional: the model's `new` is the
    source of truth for what the line should say after the edit."""
    p = workspace / "x.py"
    p.write_text("message = “hello”\n", encoding="utf-8")
    setup_read(p)
    edit_file.run({"path": str(p), "old": 'message = "hello"', "new": 'message = "world"'})
    after = p.read_text(encoding="utf-8")
    assert "world" in after
    assert "hello" not in after


def test_preview_returns_diff(workspace: Path):
    p = workspace / "x.py"
    p.write_text("a\nb\n")
    setup_read(p)
    out = edit_file.preview({"path": str(p), "old": "a", "new": "A"})
    assert "+A" in out
    assert "-a" in out
    # File untouched by preview.
    assert p.read_text() == "a\nb\n"


def test_preview_empty_on_bad_input(workspace: Path):
    p = workspace / "x.py"
    p.write_text("a\n")
    setup_read(p)
    assert edit_file.preview({"path": str(p), "old": "GHOST", "new": "x"}) == ""


def test_empty_edit_call_fails_validation_before_approval(workspace: Path):
    p = workspace / "x.py"
    p.write_text("a\n")
    setup_read(p)

    ok, msg = registry.dispatch("edit_file", {"path": str(p)}, render=False)

    assert ok is False
    assert "provide old+new" in msg
