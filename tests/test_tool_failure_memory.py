from __future__ import annotations

from pathlib import Path

from core import settings, tool_failure_memory


def test_tool_failure_memory_records_recurring_signature(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    first = tool_failure_memory.record_failure(
        workspace,
        tool="multi_edit",
        error_text="schema validation failed: edits must be non-empty",
        args={"path": "app.js", "edits": []},
    )
    second = tool_failure_memory.record_failure(
        workspace,
        tool="multi_edit",
        error_text="schema validation failed: edits must be non-empty",
        args={"path": "app.js", "edits": []},
    )

    snapshot = tool_failure_memory.snapshot(workspace)
    assert first.signature == second.signature
    assert snapshot["total"] == 1
    assert snapshot["recurring"] == 1
    assert snapshot["patterns"][0]["count"] == 2
    assert snapshot["patterns"][0]["kind"] == "schema_validation"
    assert "exact schema" in snapshot["patterns"][0]["recovery_hint"]


def test_tool_failure_memory_marks_successful_recovery(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    tool_failure_memory.record_event(
        workspace,
        {
            "event": "toolResult",
            "tool": "edit_file",
            "ok": False,
            "text": "PermissionError: read-before-edit invariant: only a partial range was read.",
        },
    )
    recovered = tool_failure_memory.record_event(
        workspace,
        {"event": "toolResult", "tool": "edit_file", "ok": True, "text": "File updated."},
    )

    assert recovered is not None
    assert recovered.kind == "read_before_edit"
    assert recovered.successful_recoveries == 1
    assert "File updated" in recovered.recovery_pattern
    assert "Tool Failure Memory" in tool_failure_memory.prompt_section(workspace)
