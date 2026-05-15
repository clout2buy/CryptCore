from __future__ import annotations

from pathlib import Path

from core import evidence, settings


def test_audit_log_records_redacted_tool_evidence(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    evidence.clear()

    evidence.record_tool_result(
        "write_file",
        {"path": "secrets.env", "content": "API_KEY=sk-abcdefghijklmnopqrstuvwxyz"},
        ok=True,
        output="wrote API_KEY=sk-abcdefghijklmnopqrstuvwxyz",
        task_id="task-1",
    )

    entries = evidence.audit_entries(task_id="task-1")
    raw = evidence.audit_path().read_text(encoding="utf-8")

    assert entries[0].phase == "changed"
    assert entries[0].summary.startswith("ok: write_file")
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in raw
    assert "[redacted]" in raw


def test_audit_summary_groups_decision_and_verification(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    evidence.clear()

    evidence.record("policy", "tool_policy", "warned about external action", task_id="task-2")
    evidence.record_verification(
        evidence.VerificationResult(status="PASS", commands=["pytest tests/test_audit_log.py"], task_id="task-2")
    )
    summary = evidence.audit_summary(task_id="task-2")

    assert "decided/tool_policy" in summary
    assert "verified/verifier" in summary
