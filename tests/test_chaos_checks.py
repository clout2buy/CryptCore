from __future__ import annotations

from pathlib import Path

from core import chaos_checks, settings


def test_chaos_checks_simulate_recoverable_failures(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    snap = chaos_checks.snapshot(workspace)

    assert snap["status"] == "pass"
    assert snap["passed"] == snap["total"]
    categories = {item["category"] for item in snap["scenarios"]}
    assert {"provider", "voice", "config", "webui", "safety", "memory"} <= categories


def test_chaos_checks_write_and_cache_report(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    report = chaos_checks.write_report(workspace)
    cached = chaos_checks.cached_snapshot(workspace)

    assert Path(report["path"]).exists()
    assert cached["status"] == "pass"
    assert cached["generatedAt"] == report["generatedAt"]
