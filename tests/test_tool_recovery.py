from __future__ import annotations

from core import tool_recovery


def test_tool_recovery_advises_stale_edit_context():
    advice = tool_recovery.advise("edit_file", {"path": "app.py"}, "file changed since Crypt read it")

    assert advice is not None
    assert advice.category == "stale-file-context"
    assert advice.retry_tool == "read_file"
    assert "newest exact text" in advice.hint


def test_tool_recovery_advises_missing_paths():
    hint = tool_recovery.format_hint("read_file", {"path": "missing.py"}, "FileNotFoundError: missing")

    assert "Recovery:" in hint
    assert "list or glob" in hint


def test_tool_recovery_compacts_large_errors():
    message = tool_recovery.compact_failure("x" * 2000, limit=120)

    assert len(message) < 180
    assert "tool error truncated" in message
