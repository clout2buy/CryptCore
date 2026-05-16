from __future__ import annotations

from pathlib import Path

from core import secret_rotation_advisor, settings


def test_secret_rotation_advisor_persists_only_sanitized_advice(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    raw_secret = "sk-testSecretValue1234567890abcdef"

    signals = secret_rotation_advisor.inspect_text(workspace, f"Use token {raw_secret} for testing", source="chat")

    assert signals
    signal = next(item for item in signals if item.kind == "openai-key")
    assert signal.severity == "critical"
    assert raw_secret not in signal.redacted_excerpt
    assert any("Revoke or rotate" in step for step in signal.checklist)

    stored = secret_rotation_advisor.advice_path(workspace).read_text(encoding="utf-8")
    assert raw_secret not in stored
    assert signal.fingerprint in stored
    assert "[redacted]" in stored

    snapshot = secret_rotation_advisor.snapshot(workspace)
    assert snapshot["total"] >= 1
    assert snapshot["critical"] >= 1
    assert snapshot["signals"][0]["fingerprint"]


def test_secret_rotation_advisor_scans_events_and_dedupes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    raw_secret = "github_pat_1234567890abcdefghijklmnopqrstuvwxyz"

    first = secret_rotation_advisor.scan_event(
        workspace,
        {"event": "toolResult", "tool": "shell", "ok": False, "text": f"GITHUB_TOKEN={raw_secret}"},
    )
    second = secret_rotation_advisor.scan_event(
        workspace,
        {"event": "toolResult", "tool": "shell", "ok": False, "text": f"GITHUB_TOKEN={raw_secret}"},
    )

    assert first
    assert second
    snapshot = secret_rotation_advisor.snapshot(workspace)
    assert snapshot["byKind"]["github-token"] == 1
    assert any(signal["seen_count"] >= 2 for signal in snapshot["signals"] if signal["kind"] == "github-token")
    assert raw_secret not in secret_rotation_advisor.prompt_section(workspace)
    assert "Secret Rotation Advisor" in secret_rotation_advisor.prompt_section(workspace)
