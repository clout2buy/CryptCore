from __future__ import annotations

from pathlib import Path

import pytest

from core import revenue, settings, webui


def test_revenue_summary_tracks_profit_funnel_and_trend(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    now = 10_000_000
    previous = now - 10 * 24 * 60 * 60
    revenue.record_event(workspace, "revenue", amount=100, channel="reddit", created_at=previous)
    revenue.record_event(workspace, "expense", amount=40, channel="ads", created_at=previous)
    revenue.record_event(workspace, "visit", amount=100, channel="reddit", created_at=now - 100)
    revenue.record_event(workspace, "lead", amount=12, channel="reddit", created_at=now - 90)
    revenue.record_event(workspace, "conversion", amount=4, channel="reddit", created_at=now - 80)
    revenue.record_event(workspace, "revenue", amount=250, channel="reddit", created_at=now - 70)
    revenue.record_event(workspace, "expense", amount=25, channel="ads", created_at=now - 60)

    summary = revenue.summarize(workspace, days=7, now=now)

    assert summary.revenue == 250
    assert summary.expenses == 25
    assert summary.profit == 225
    assert summary.conversion_rate == pytest.approx(0.04)
    assert summary.revenue_delta == 150
    assert summary.profit_delta == 165
    assert summary.top_channels[0]["channel"] == "reddit"


def test_revenue_dashboard_snapshot_and_prompt(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    revenue.record_event(workspace, "revenue", amount=19, channel="site")

    snapshot = revenue.dashboard_snapshot(workspace)
    section = revenue.prompt_section(workspace)

    assert snapshot["summary"]["revenue"] == 19
    assert "Revenue And Metrics" in section
    assert "profit" in section


def test_webui_snapshot_includes_revenue(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    revenue.record_event(workspace, "lead", amount=3, channel="email")
    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        snapshot = handler_obj._snapshot()
    finally:
        server.server_close()

    assert snapshot["revenue"]["summary"]["leads"] == 3
