from __future__ import annotations

import time
from pathlib import Path

from core import revenue, revenue_ops, settings, webui


def test_revenue_ops_forecasts_targets_and_actions(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    now = int(time.time())

    revenue.record_event(workspace, "visit", amount=100, channel="reddit", created_at=now - 100)
    revenue.record_event(workspace, "lead", amount=5, channel="reddit", created_at=now - 90)
    revenue.record_event(workspace, "revenue", amount=120, channel="reddit", created_at=now - 80)
    revenue.record_event(workspace, "expense", amount=40, channel="ads", created_at=now - 70)
    target = revenue_ops.set_target(workspace, "First $500 launch", target_revenue=500, target_profit=300)

    dashboard = revenue_ops.dashboard(workspace, days=30)

    assert dashboard["summary"]["revenue"] == 120
    assert dashboard["forecast"]["revenue30d"] == 120
    assert dashboard["targets"][0]["target_id"] == target.target_id
    assert dashboard["targets"][0]["gapRevenue"] == 380
    assert dashboard["channels"][0]["channel"] == "reddit"
    assert any("First $500 launch" in action for action in dashboard["nextActions"])


def test_revenue_ops_prompt_reaches_webui_context(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    revenue.record_event(workspace, "lead", amount=3, channel="email")
    revenue_ops.set_target(workspace, "Weekly sales push", target_revenue=200)

    text = webui._prompt_with_context("Track revenue and tell me next action", [], workspace=workspace)

    assert "Revenue Operations" in text
    assert "Weekly sales push" in text
