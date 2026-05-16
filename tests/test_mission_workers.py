from __future__ import annotations

from pathlib import Path

from core import job_queue, mission_workers, settings


def test_mission_worker_blocks_external_actions_until_approved(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    worker = mission_workers.create_worker(
        workspace,
        "Promote launch on Reddit",
        prompt="Draft and post a launch note to Reddit.",
    )
    blocked = mission_workers.run_cycle(workspace, worker.worker_id, now=1000)

    assert blocked.status == "blocked"
    assert blocked.external_gate_required is True
    assert blocked.external_approved is False
    assert "external access" in blocked.gate_reason.lower() or "approval" in blocked.gate_reason.lower()
    assert job_queue.snapshot(workspace)["queued"] == 0


def test_mission_worker_queues_cycles_after_external_approval(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    worker = mission_workers.create_worker(workspace, "Research leads", prompt="Research leads and draft outreach.")

    approved = mission_workers.approve_external(workspace, worker.worker_id, note="drafting only approved")
    cycled = mission_workers.run_cycle(workspace, approved.worker_id, now=1000)
    snap = mission_workers.snapshot(workspace)

    assert cycled.status == "active"
    assert cycled.cycle_count == 1
    assert cycled.last_job_id
    assert snap["active"] == 1
    assert job_queue.snapshot(workspace)["queued"] == 1
    assert "Long-Running Mission Workers" in mission_workers.prompt_section(workspace)
