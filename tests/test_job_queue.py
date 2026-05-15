from __future__ import annotations

from core import job_queue, settings, webui


def test_job_queue_persists_logs_completion_and_cancellation(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    job = job_queue.enqueue(workspace, "Build launch site", prompt="ship homepage", priority=5)
    started = job_queue.start(workspace, job.job_id)
    logged = job_queue.append_log(workspace, job.job_id, "generated files")
    done = job_queue.complete(workspace, job.job_id, result="verified")

    assert started.status == "running"
    assert logged.logs[-1].text == "generated files"
    assert done.status == "succeeded"
    assert done.result == "verified"
    assert job_queue.snapshot(workspace)["total"] == 1

    second = job_queue.enqueue(workspace, "Cancel me")
    cancelled = job_queue.cancel(workspace, second.job_id, reason="user stopped it")
    assert cancelled.cancel_requested is True
    assert cancelled.status == "cancelled"


def test_job_queue_recovery_marks_running_jobs_interrupted(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    job = job_queue.enqueue(workspace, "Long job")
    job_queue.start(workspace, job.job_id)

    recovered = job_queue.recover(workspace)

    assert len(recovered) == 1
    assert recovered[0].status == "interrupted"
    assert "Job Queue" in job_queue.prompt_section(workspace)


def test_webui_recovers_job_queue_on_start(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    job = job_queue.enqueue(workspace, "Runtime job")
    job_queue.start(workspace, job.job_id)

    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        assert job_queue.snapshot(workspace)["interrupted"] == 1
    finally:
        server.server_close()
