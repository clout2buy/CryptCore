from __future__ import annotations

from pathlib import Path

from core import intent_router, mission_router, settings, task_contracts, work_threads


def test_task_contracts_convert_vague_business_request(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    text = "Build me a small business that tracks income and can post launch updates later."
    route = intent_router.route(text)
    mission = mission_router.observe(workspace, text, route=route)
    thread = work_threads.ensure_for_goal(mission.goal, prompt_text=text) if mission.goal else None

    contract = task_contracts.ensure_for_prompt(workspace, text, route=route, mission=mission, thread=thread)

    assert contract is not None
    assert contract.intent == "business"
    assert contract.mission_id
    assert contract.thread_id
    assert contract.external_gates
    assert any("approval" in gate.lower() for gate in contract.external_gates)
    assert any("tracking" in check.lower() or "revenue" in check.lower() for check in contract.acceptance_checks)
    assert task_contracts.snapshot(workspace)["approvalGated"] == 1
    assert "Structured Task Contracts" in task_contracts.prompt_section(workspace)


def test_task_contracts_skip_short_conversation(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    route = intent_router.route("hey")

    contract = task_contracts.ensure_for_prompt(workspace, "hey", route=route)

    assert contract is None
    assert task_contracts.snapshot(workspace)["total"] == 0
