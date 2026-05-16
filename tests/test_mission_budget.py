from __future__ import annotations

from pathlib import Path

from core import goals, mission_budget, model_usage_ledger, settings, work_threads


def test_mission_budget_tracks_thread_budget_and_spend(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal("Launch tiny business", workspace=workspace, priority=5)
    thread = work_threads.ensure_for_goal(goal, prompt_text="build site and track revenue")

    mission_budget.set_budget(
        workspace,
        goal.goal_id,
        goal.title,
        max_cost_usd=0.01,
        max_minutes=30,
        risk_budget="high",
        revenue_target_usd=100,
    )
    mission_budget.record_spend(workspace, goal.goal_id, minutes=45, model_cost_usd=0.02, note="prototype run")

    snapshot = mission_budget.snapshot(workspace)
    card = next(item for item in snapshot["cards"] if item["missionId"] == goal.goal_id)

    assert thread.goal_id == goal.goal_id
    assert snapshot["overBudget"] == 1
    assert card["status"] == "over-budget"
    assert card["riskBudget"] == "high"
    assert card["revenueTargetUsd"] == 100
    assert "Mission Budget Ledger" in mission_budget.prompt_section(workspace)


def test_mission_budget_includes_workspace_model_usage(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    model_usage_ledger.record_run(
        workspace,
        provider="openai",
        model="gpt-5.3",
        task_id="task-1",
        total_tokens=1000,
    )

    snapshot = mission_budget.snapshot(workspace)

    assert snapshot["workspaceTokensEstimated"] == 1000
    assert snapshot["workspaceModelCostUsd"] > 0
