from __future__ import annotations

from pathlib import Path

import pytest

from core import agent_profiles, multi_agent_threads, settings, webui


def _agent(workspace: Path, name: str) -> agent_profiles.AgentProfile:
    return agent_profiles.create_profile(
        workspace,
        name=name,
        purpose=f"{name} test work.",
        agent_type="worker",
        provider="crypt",
        model="crypt-pro",
    )


def test_multi_agent_thread_completes_independent_assignments(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ui_agent = _agent(workspace, "UI Worker")
    api_agent = _agent(workspace, "API Worker")

    thread = multi_agent_threads.create_thread(
        workspace,
        "Ship dashboard upgrade",
        [
            {
                "agent_id": ui_agent.id,
                "responsibility": "Rebuild dashboard UI",
                "write_scope": ["core/webui_static/app.js"],
            },
            {
                "agent_id": api_agent.id,
                "responsibility": "Update snapshot API",
                "write_scope": ["core/webui.py"],
            },
        ],
    )
    first = thread.assignments[0]
    second = thread.assignments[1]

    thread = multi_agent_threads.complete_assignment(
        workspace,
        thread.thread_id,
        first.item_id,
        result="UI rebuilt",
        artifacts=["core/webui_static/app.js"],
        review="Looks clean.",
    )
    assert thread.state == "active"
    thread = multi_agent_threads.complete_assignment(
        workspace,
        thread.thread_id,
        second.item_id,
        result="Snapshot updated",
        artifacts=["core/webui.py"],
    )

    assert thread.state == "merged"
    assert "UI rebuilt" in thread.merge_summary
    assert "core/webui.py" in thread.merge_summary


def test_multi_agent_thread_rejects_write_scope_conflict(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    with pytest.raises(ValueError, match="write scope conflict"):
        multi_agent_threads.create_thread(
            workspace,
            "Conflicting work",
            [
                {"agent_name": "A", "responsibility": "first", "write_scope": ["core/webui.py"]},
                {"agent_name": "B", "responsibility": "second", "write_scope": ["core\\webui.py"]},
            ],
        )


def test_webui_snapshot_and_prompt_include_multi_agent_threads(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    multi_agent_threads.create_thread(
        workspace,
        "Parallel release prep",
        [
            {"agent_name": "Reviewer", "responsibility": "Review changes", "write_scope": ["docs/review.md"]},
            {"agent_name": "Verifier", "responsibility": "Run checks", "write_scope": ["docs/checks.md"]},
        ],
    )

    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        snapshot = handler_obj._snapshot()
    finally:
        server.server_close()
    prompt = webui._prompt_with_context("finish release prep", [], workspace=workspace)

    assert snapshot["multiAgentThreads"]["count"] == 1
    assert "Multi-Agent Work Threads" in prompt
