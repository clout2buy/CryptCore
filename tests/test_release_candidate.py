from __future__ import annotations

from pathlib import Path

from core import release_candidate, settings


def test_release_candidate_snapshot_before_generation(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    snap = release_candidate.snapshot(workspace, {"chaosChecks": {"status": "pass"}, "repairDoctor": {"status": "ready"}})

    assert snap["version"] == "1.0-rc"
    assert snap["status"] == "not-generated"
    assert "push_package" in snap


def test_release_candidate_generate_writes_manifest(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    rc = release_candidate.generate(
        workspace,
        checks=['python -c "print(123)"'],
        output_root=tmp_path / "rc-output",
    )

    assert rc["version"] == "1.0-rc"
    assert Path(rc["release_checklist"]).exists()
    assert Path(rc["chaos_report"]).exists()
    assert Path(rc["eval_report"]).exists()
    assert release_candidate.latest_path(workspace).exists()
    assert "git push origin main" in "\n".join(rc["push_package"])
