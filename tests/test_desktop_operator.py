from __future__ import annotations

from core import desktop_operator


def test_desktop_operator_plans_visible_actions():
    job = desktop_operator.plan("move the mouse, click settings, and take a screenshot")

    actions = [step.action for step in job.steps]
    assert job.mode == "visual-desktop"
    assert actions[:2] == ["inspect-screen", "move-pointer"]
    assert "click" in actions
    assert "capture-screen" in actions
    assert "Inspect the current visible desktop state" in desktop_operator.narration(job)


def test_desktop_operator_gates_sensitive_actions():
    job = desktop_operator.plan("login and type my password into the app")

    assert job.approval_required is True
    assert job.mode == "approval-gated-desktop"
    assert any(step.requires_approval for step in job.steps if step.action == "type")
