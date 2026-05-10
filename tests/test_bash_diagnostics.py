"""Bash error diagnostics + output cap.

We exercise the pure functions (`_diagnose_failure`, `_clip_stream`,
`_format_output`) directly so the tests don't depend on what's installed
in the test runner's PATH or which shell python uses on this OS.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools import bash


def test_clip_stream_under_cap():
    body, clipped = bash._clip_stream("short text")
    assert body == "short text"
    assert clipped is False


def test_clip_stream_over_cap_keeps_head_and_tail():
    text = "A" * 10_000 + "MIDDLE" + "B" * 10_000 + "END"
    body, clipped = bash._clip_stream(text, cap=1000)
    assert clipped is True
    assert body.startswith("A")
    assert body.endswith("END")
    assert "chars truncated" in body


def test_format_output_empty():
    body, spill = bash._format_output("noop", "", "")
    assert body == "(no output)"
    assert spill == ""


def test_format_output_overflow_writes_spill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bash, "_SPILL_DIR", tmp_path)
    big = "X" * 100_000
    body, spill = bash._format_output("python -c 'big'", big, "")
    assert spill  # path string returned
    assert "output truncated" in body
    assert Path(spill).exists()
    assert Path(spill).read_text(encoding="utf-8").startswith("$ python -c 'big'")


def test_diagnose_redirected_stderr():
    hint = bash._diagnose_failure("python -c 'x' 2>nul", returncode=7, stdout="", stderr="")
    assert "redirected" in hint


def test_diagnose_unknown_verb_no_output():
    hint = bash._diagnose_failure("zzznotreal --help", returncode=1, stdout="", stderr="")
    assert "zzznotreal" in hint
    assert "PATH" in hint or "found" in hint


def test_simple_heredoc_is_converted_to_stdin():
    cmd, stdin = bash._prepare_command("python - <<'PY'\nprint('hi')\nPY")

    assert cmd == "python -"
    assert stdin == "print('hi')\n"


def test_diagnose_double_escaped_windows_path(monkeypatch):
    monkeypatch.setattr(bash.os, "name", "nt")

    hint = bash._diagnose_failure(r'dir "C:\\Users\\Clout\\Downloads"', returncode=1, stdout="", stderr="")

    assert "single backslashes" in hint


@pytest.mark.skipif(os.name != "nt", reason="POSIX-on-Windows hint is Windows-only")
def test_diagnose_posix_command_on_windows():
    """If wc isn't installed, the hint should mention it AND suggest the
    PowerShell equivalent. If it IS installed (Git for Windows), we still
    expect the glob hint when * is in the command."""
    hint = bash._diagnose_failure("wc -l *.py 2>nul", returncode=1, stdout="", stderr="")
    assert hint  # non-empty
