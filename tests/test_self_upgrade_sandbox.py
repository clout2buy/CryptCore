from __future__ import annotations

from pathlib import Path

from core import learning, self_upgrade_sandbox, settings, upgrade_queue


def test_self_upgrade_sandbox_plans_from_upgrade_idea(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    learning.record_user_correction(workspace, "Nope, make live thinking render immediately.")
    idea = upgrade_queue.suggest(workspace)[0]

    record = self_upgrade_sandbox.plan_from_idea(workspace, idea.idea_id)
    snapshot = self_upgrade_sandbox.snapshot(workspace)

    assert record.idea_id == idea.idea_id
    assert record.branch.startswith("codex/upgrade-")
    assert "verify_core.ps1 -Quick" in "; ".join(record.checks)
    assert snapshot["total"] == 1
    assert snapshot["statusCounts"]["planned"] == 1


def test_self_upgrade_sandbox_records_results_and_merge_proposal(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    record = self_upgrade_sandbox.plan(workspace, title="Improve provider routing")

    verified = self_upgrade_sandbox.record_result(
        workspace,
        record.sandbox_id,
        status="verified",
        checks=["pytest tests/test_smart_model_router.py"],
        changed_paths=["core/smart_model_router.py"],
        note="focused check passed",
    )
    proposed = self_upgrade_sandbox.propose_merge(workspace, record.sandbox_id)
    section = self_upgrade_sandbox.prompt_section(workspace)

    assert verified.status == "verified"
    assert verified.changed_paths == ["core/smart_model_router.py"]
    assert proposed.status == "proposed"
    assert "Self-Upgrade Sandbox" in section
