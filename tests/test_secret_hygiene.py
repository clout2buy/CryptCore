from __future__ import annotations

from pathlib import Path

from core import secret_hygiene


def test_secret_hygiene_scans_text_with_redacted_excerpt():
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    findings = secret_hygiene.scan_text(f"OPENAI_API_KEY={secret}", file="config.env")

    assert findings
    assert findings[0].kind in {"openai-key", "secret-assignment"}
    assert secret not in findings[0].excerpt
    assert "[redacted]" in findings[0].excerpt


def test_secret_hygiene_scans_workspace_and_skips_junk(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / ".env").write_text("TOKEN=ghp_abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "leak.txt").write_text("PASSWORD=should_not_scan\n", encoding="utf-8")

    findings = secret_hygiene.scan_workspace(workspace)
    summary = secret_hygiene.summary(findings)

    assert len(findings) == 1
    assert findings[0].file == ".env"
    assert "github-token" in summary or "secret-assignment" in summary
    assert "abcdefghijklmnopqrstuvwxyz" not in findings[0].excerpt


def test_safe_context_redacts_nested_content():
    data = {"message": "password=super-secret-value"}

    safe = secret_hygiene.safe_context(data)

    assert safe["message"] == "password=[redacted]"
