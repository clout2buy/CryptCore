from __future__ import annotations

from pathlib import Path

from core import runtime_compactor, settings


def test_runtime_compactor_summarizes_large_snapshot(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    snapshot = {
        "workspace": "repo",
        "provider": "crypt",
        "model": "crypt-max",
        "jobQueue": {"interrupted": 1, "jobs": [{"title": "a" * 400, "status": "running"} for _ in range(20)]},
        "repairDoctor": {"failing": 2, "summary": "repair me"},
        "notifications": {"critical": 1, "items": [{"title": "Approval", "severity": "approval"}]},
        "messages": [{"content": "x" * 1000} for _ in range(25)],
    }

    compacted = runtime_compactor.compact(snapshot)

    assert compacted["totalKeys"] == len(snapshot)
    assert compacted["compactChars"] < compacted["estimatedChars"]
    assert compacted["summary"]["jobQueue"]["jobs"]["count"] == 20
    assert compacted["warnings"]


def test_runtime_compactor_writes_project_snapshot(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    data = runtime_compactor.write_compact(workspace, {"workspace": str(workspace), "goals": [1, 2, 3]})

    assert Path(data["path"]).exists()
    assert "Runtime State Compact" in runtime_compactor.prompt_section({"workspace": str(workspace)})
