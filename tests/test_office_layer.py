from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from core import artifact_studio, office_layer, settings


def test_office_layer_creates_and_registers_markdown_brief(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    record = office_layer.create_markdown_brief(
        workspace,
        "Launch Ops Brief",
        {"Plan": "Track revenue, leads, and weekly blockers."},
        purpose="business operating brief",
    )

    assert record.kind == "document"
    assert record.status == "verified"
    assert "Track revenue" in record.preview
    assert (workspace / "office" / "launch-ops-brief.md").exists()
    assert office_layer.snapshot(workspace)["verified"] == 1
    assert artifact_studio.snapshot(workspace)["summary"]["total"] == 1
    assert "Office Artifacts" in office_layer.prompt_section(workspace)


def test_office_layer_verifies_office_zip_packages(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    docx = workspace / "proposal.docx"
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types />")
        zf.writestr("word/document.xml", "<document>Proposal</document>")

    record = office_layer.register(workspace, docx, purpose="client proposal")

    assert record.kind == "document"
    assert record.status == "verified"
    assert any("PASS docx document body" in check for check in record.checks)


def test_office_layer_rejects_unsupported_types(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    script = workspace / "demo.py"
    script.write_text("print('x')\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported"):
        office_layer.register(workspace, script)
