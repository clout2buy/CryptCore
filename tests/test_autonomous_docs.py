from __future__ import annotations

from pathlib import Path

from core import autonomous_docs, settings


def test_autonomous_docs_writes_user_facing_guide(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    runtime = {
        "coreFeatures": [
            {"label": "Missions"},
            {"label": "Memory"},
            {"label": "Screenshot Memory"},
            {"label": "External Receipts"},
            {"label": "Credential Vault"},
        ],
        "capabilityMatrix": {
            "total": 3,
            "capabilities": [
                {"label": "Voice loop", "status": "ready"},
                {"label": "Mission brain", "status": "ready"},
                {"label": "External actions", "status": "approval-gated"},
            ],
        },
    }

    snap = autonomous_docs.snapshot(workspace, runtime)
    guide = Path(snap["path"])
    text = guide.read_text(encoding="utf-8")

    assert guide.exists()
    assert snap["sectionCount"] >= 6
    assert snap["capabilityCount"] == 3
    assert "Talk To Crypt" in text
    assert "External Actions" in text
    assert "core." not in text
    assert "schema" not in text.lower()
    assert "Autonomous Documentation Writer" in autonomous_docs.prompt_section(workspace)


def test_autonomous_docs_rebuilds_when_capability_count_changes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    first = autonomous_docs.snapshot(workspace, {"capabilityMatrix": {"total": 1, "capabilities": []}})
    second = autonomous_docs.snapshot(workspace, {"capabilityMatrix": {"total": 2, "capabilities": []}})

    assert first["capabilityCount"] == 1
    assert second["capabilityCount"] == 2
    assert second["wordCount"] >= first["wordCount"]
