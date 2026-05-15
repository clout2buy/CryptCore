from __future__ import annotations

from core import model_usage_ledger, settings


def test_model_usage_ledger_records_latency_success_and_estimated_cost(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    run = model_usage_ledger.record_run(
        workspace,
        provider="crypt",
        model="gpt-5.5",
        task_id="task_1",
        task_type="builder",
        ok=True,
        latency_ms=1234,
        total_tokens=1000,
    )

    assert run.input_tokens_est == 800
    assert run.output_tokens_est == 200
    assert run.cost_usd_est > 0
    snap = model_usage_ledger.snapshot(workspace)
    assert snap["total"] == 1
    assert snap["success"] == 1
    assert snap["tokensEstimated"] == 1000
    assert snap["avgLatencyMs"] == 1234
    assert "Model Usage Ledger" in model_usage_ledger.prompt_section(workspace)


def test_model_usage_ledger_groups_failures_by_model(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    model_usage_ledger.record_run(workspace, provider="ollama", model="local", ok=False, latency_ms=20, error="offline")
    model_usage_ledger.record_run(workspace, provider="ollama", model="local", ok=True, latency_ms=10, total_tokens=50)
    snap = model_usage_ledger.snapshot(workspace)

    assert snap["failed"] == 1
    assert snap["byModel"][0]["runs"] == 2
    assert snap["byModel"][0]["costEstimatedUsd"] == 0.0
