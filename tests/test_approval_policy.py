from __future__ import annotations

from core import approval_policy, settings


def test_approval_policy_defaults_gate_external_actions(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    decision = approval_policy.decide(workspace, "Post this launch on Reddit", intent="external_action")

    assert decision.action == "ask"
    assert decision.approval_required is True
    assert decision.risk == "critical"
    snap = approval_policy.snapshot(workspace)
    assert snap["enabled"] >= 5
    assert snap["ask"] >= 3
    assert "Approval Policy" in approval_policy.prompt_section(workspace, "Post this")


def test_approval_policy_custom_rule_blocks_matching_work(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    rule = approval_policy.upsert_rule(
        workspace,
        title="No casino content",
        action="block",
        match="casino|gambling",
        risk="high",
        reason="User does not want gambling work.",
    )
    decision = approval_policy.decide(workspace, "Write a casino ad")

    assert decision.action == "block"
    assert decision.rule_id == rule.rule_id
    disabled = approval_policy.set_enabled(workspace, rule.rule_id, False)
    assert disabled.enabled is False
