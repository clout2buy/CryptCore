from __future__ import annotations

import subprocess
import time
from pathlib import Path

from core import (
    background,
    evidence,
    final_claims,
    loop,
    redact,
    runtime,
    settings,
    tool_policy,
    tool_recovery,
    verifiers,
    worktrees,
)
from core.api import TurnEnd
from core.agents import orchestrator
from core import ui
from core.agents import registry as agent_registry
from core.agents import tasks as agent_tasks
from tools import REGISTRY, dispatch
from tools import agent as agent_tool
from tools import agent_output as agent_output_tool
from tools import bash as bash_tool
from tools import cleanup_agent as cleanup_agent_tool
from tools.types import Tool


def teardown_function():
    evidence.clear()
    tool_policy.clear()
    agent_tasks.reset()


def test_agent_registry_has_production_roles():
    names = set(agent_registry.agent_names())

    assert {"explorer", "planner", "worker", "verifier", "ui_reviewer", "release_reviewer"} <= names
    worker = agent_registry.get_agent("worker")
    verifier = agent_registry.get_agent("verifier")
    assert worker.requires_write_paths is True
    assert worker.can_write is True
    assert "edit_file" in worker.allowed_tools
    assert verifier.read_only is True


def test_orchestrator_classifies_upgrade_audit_as_repo_investigation():
    assert orchestrator.classify("really understand it and lmk what we can upgrade") == "repo_investigation"
    assert orchestrator.requires_agent("really understand it and lmk what we can upgrade") is True


def test_redact_masks_target_file_secret_assignments():
    text = "\n".join([
        "     1\u2192DISCORD_TOKEN=redaction-fixture-not-a-real-token",
        "     2\u2192OWNER_ID=1129954690180849674",
        "     3\u2192ADMIN_WEB_TOKEN=local-admin",
    ])

    redacted = redact.text(text)

    assert "redaction-fixture" not in redacted
    assert "local-admin" not in redacted
    assert "DISCORD_TOKEN=[redacted]" in redacted
    assert "ADMIN_WEB_TOKEN=[redacted]" in redacted
    assert "OWNER_ID=1129954690180849674" in redacted


def test_redact_masks_line_numbered_secret_assignments():
    redacted = redact.text("     7\u2192API_TOKEN=super-secret-value\n  8->PASSWORD: hunter2")

    assert "super-secret-value" not in redacted
    assert "hunter2" not in redacted
    assert "API_TOKEN=[redacted]" in redacted
    assert "PASSWORD: [redacted]" in redacted


def test_read_or_open_satisfies_write_loop_guard(tmp_path):
    runtime.configure(None, str(tmp_path), session=None)
    path = tmp_path / "admin.css"
    args = {"path": str(path), "old": "a", "new": "b"}

    for i in range(3):
        tool_policy.after_tool("edit_file", {"path": str(path), "old": str(i), "new": str(i + 1)}, ok=True)

    blocked = tool_policy.preflight("edit_file", args)
    assert blocked.action == tool_policy.BLOCK

    tool_policy.after_tool("read_file", {"path": str(path)}, ok=True)

    allowed = tool_policy.preflight("edit_file", args)
    assert allowed.action == tool_policy.ALLOW


def test_orchestrator_guidance_requires_agent_for_audit():
    guidance = orchestrator.guidance_for_turn([
        {"role": "user", "content": "really understand it and lmk what we can upgrade"},
    ])

    assert "requires autonomous delegation" in guidance
    assert "spawn at least one explorer or planner agent" in guidance


def test_orchestrator_uses_previous_task_for_short_focus_ack():
    messages = [
        {"role": "user", "content": "really understand it and lmk what we can upgrade"},
        {"role": "assistant", "content": [{"type": "text", "text": "I will inspect it."}]},
        {"role": "user", "content": "ok focus"},
    ]

    assert orchestrator.task_text(messages) == "really understand it and lmk what we can upgrade"


def test_orchestrator_retries_promise_without_tool_work():
    messages = [{"role": "user", "content": "really understand it and lmk what we can upgrade"}]
    assistant = {"role": "assistant", "content": [{"type": "text", "text": "I will audit it and come back."}]}

    assert orchestrator.should_retry_text_only(messages, assistant) is True
    correction = orchestrator.tool_retry_message(messages)
    assert "spawn_agent" in correction["content"][0]["text"]


def test_orchestrator_does_not_retry_after_successful_inspection_tool():
    messages = [
        {"role": "user", "content": "inspect README only"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "README.md"}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "ok"}],
        },
    ]
    assistant = {"role": "assistant", "content": [{"type": "text", "text": "Here is what README says."}]}

    assert orchestrator.should_retry_text_only(messages, assistant) is False


def test_orchestrator_retries_audit_final_without_agent_even_after_direct_read():
    messages = [
        {"role": "user", "content": "really understand it and lmk what we can upgrade"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "README.md"}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "ok"}],
        },
    ]
    assistant = {"role": "assistant", "content": [{"type": "text", "text": "Here is the audit."}]}

    assert orchestrator.should_retry_text_only(messages, assistant) is True


def test_orchestrator_allows_audit_final_after_spawn_agent():
    messages = [
        {"role": "user", "content": "really understand it and lmk what we can upgrade"},
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "call_1",
                "name": "spawn_agent",
                "input": {"description": "audit", "prompt": "audit", "agent_type": "explorer"},
            }],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "agent report"}],
        },
    ]
    assistant = {"role": "assistant", "content": [{"type": "text", "text": "Here is the audit."}]}

    assert orchestrator.should_retry_text_only(messages, assistant) is False


def test_tool_recovery_detects_invalid_empty_edit_payload():
    messages = [
        {"role": "user", "content": "code it all"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "call_1", "name": "edit_file", "input": {"path": "x.py", "edits": []}}],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": "schema validation failed: edits: expected a non-empty array",
                "is_error": True,
            }],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "Implemented partway, can continue."}]},
    ]

    assert tool_recovery.should_retry_after_tool_failure(messages, messages[-1]) is True
    correction = tool_recovery.recovery_message(messages)
    assert "retry the failed edit/write" in correction["content"][0]["text"]


def test_tool_recovery_detects_bash_platform_hint():
    messages = [
        {"role": "user", "content": "run the check"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "call_1", "name": "bash", "input": {"command": "wc -l *.py"}}],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": "RuntimeError: exit 1\n(no output)\n[hint: `wc` is a POSIX command not installed on this Windows shell.]",
                "is_error": True,
            }],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "I can try something else later."}]},
    ]

    assert tool_recovery.should_retry_after_tool_failure(messages, messages[-1]) is True
    correction = tool_recovery.recovery_message(messages)
    assert "bash" in correction["content"][0]["text"]


def test_tool_recovery_stops_repeated_edit_spiral():
    messages = [{"role": "user", "content": "change the colors"}]
    for idx, tool_name in enumerate(["edit_file", "multi_edit", "edit_file"], start=1):
        messages.append({
            "role": "assistant",
            "content": [{"type": "tool_use", "id": f"call_{idx}", "name": tool_name, "input": {"path": "prototype.html"}}],
        })
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": f"call_{idx}",
                "content": "schema validation failed: edits: expected a non-empty array",
                "is_error": True,
            }],
        })

    assert tool_recovery.should_stop_after_failure_spiral(messages) is True
    stop = tool_recovery.spiral_stop_message(messages)
    assert "I stopped before retrying" in stop["content"][0]["text"]


def test_loop_stops_after_repeated_recoverable_edit_failures(tmp_path):
    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = False
        context_window = 100_000

        def __init__(self):
            self.calls = 0

        def stream_turn(self, messages, tools, system):
            self.calls += 1
            if self.calls > 3:
                raise AssertionError("loop should stop before another blind retry")
            yield TurnEnd(
                stop_reason="tool_use",
                message={
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": f"call_{self.calls}",
                        "name": "edit_file",
                        "input": {"path": "prototype.html", "edits": []},
                    }],
                },
            )

    provider = Provider()
    previous = runtime.approval_mode()
    runtime.set_approval_mode(runtime.APPROVAL_ALL)
    try:
        runtime.configure(provider, str(tmp_path), session=None)
        messages = [{"role": "user", "content": "change the colors"}]

        loop._run_until_done(provider, messages, 0, 0, render=False)
    finally:
        runtime.set_approval_mode(previous)

    assert provider.calls == 3
    assert "I stopped before retrying" in messages[-1]["content"][0]["text"]


def test_loop_retries_after_recoverable_tool_validation_failure(tmp_path):
    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = False
        context_window = 100_000

        def __init__(self):
            self.calls = 0

        def stream_turn(self, messages, tools, system):
            self.calls += 1
            if self.calls == 1:
                yield TurnEnd(
                    stop_reason="tool_use",
                    message={
                        "role": "assistant",
                        "content": [{
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "edit_file",
                            "input": {"path": "missing.py", "edits": []},
                        }],
                    },
                )
                return
            if self.calls == 2:
                yield TurnEnd(
                    stop_reason="end_turn",
                    message={
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Implemented partway, I can continue."}],
                    },
                )
                return
            assert any(
                isinstance(msg.get("content"), list)
                and any(
                    isinstance(block, dict)
                    and "previous tool calls failed because their arguments were invalid" in str(block.get("text", ""))
                    for block in msg["content"]
                )
                for msg in messages
            )
            yield TurnEnd(
                stop_reason="end_turn",
                message={"role": "assistant", "content": [{"type": "text", "text": "Recovered with a concrete next step."}]},
            )

    provider = Provider()
    runtime.configure(provider, str(tmp_path), session=None)
    messages = [{"role": "user", "content": "fix one missing import"}]

    loop._run_until_done(provider, messages, 0, 0, render=False)

    assert provider.calls == 3
    assert "Recovered with a concrete next step." in messages[-1]["content"][0]["text"]


def test_subagent_schema_uses_typed_agent_tool_surface():
    default_names = {item["name"] for item in REGISTRY.schemas(for_subagent=True)}
    assert "edit_file" not in default_names

    worker = agent_registry.get_agent("worker")
    with runtime.subagent_context(
        agent_type="worker",
        allowed_tools=worker.allowed_tools,
        write_paths=["core"],
        task_id="agent_test",
    ):
        worker_names = {item["name"] for item in REGISTRY.schemas(for_subagent=True)}

    assert "edit_file" in worker_names
    assert "multi_edit" in worker_names
    assert "spawn_agent" not in worker_names


def test_subagent_ask_tool_requires_safe_classifier_or_write_scope(monkeypatch):
    tool = Tool(
        name="ask_stub_runtime",
        description="ask stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="ask",
        run=lambda args: "ran",
    )
    monkeypatch.setitem(REGISTRY._tools, tool.name, tool)

    with runtime.subagent_context(
        agent_type="explorer",
        allowed_tools={tool.name},
        write_paths=[],
        task_id="agent_safe",
    ):
        ok, msg = dispatch(tool.name, {"x": "hi"}, render=False)

    assert ok is False
    assert "approval required" in msg

    safe_tool = Tool(
        name="safe_ask_stub_runtime",
        description="safe ask stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="ask",
        run=lambda args: "ran",
        classify=lambda args: "safe",
    )
    monkeypatch.setitem(REGISTRY._tools, safe_tool.name, safe_tool)
    with runtime.subagent_context(
        agent_type="explorer",
        allowed_tools={safe_tool.name},
        write_paths=[],
        task_id="agent_safe",
    ):
        ok, msg = dispatch(safe_tool.name, {"x": "hi"}, render=False)

    assert ok is True
    assert msg == "ran"


def test_spawn_agent_worker_requires_write_paths():
    out = agent_tool.run({
        "description": "worker missing scope",
        "agent_type": "worker",
        "prompt": "change something",
    })

    assert "non-empty write_paths" in out


def test_spawn_agent_sync_uses_runtime_runner(tmp_path):
    runtime.configure(
        provider=None,
        cwd=str(tmp_path),
        subagent_runner=lambda prompt, context=None, **kwargs: (
            f"{kwargs['agent_type']}:{kwargs['write_paths']}:{prompt[:5]}"
        ),
    )

    out = agent_tool.run({
        "description": "inspect",
        "agent_type": "explorer",
        "prompt": "hello world",
    })

    assert "explorer:[]:hello" in out
    listed = agent_tasks.list_tasks()
    assert len(listed) == 1
    assert listed[0].status.value == "completed"


def test_spawn_agent_worktree_isolation_passes_worktree_path(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    seen: dict[str, str] = {}

    def runner(prompt, context=None, **kwargs):
        seen["worktree_path"] = kwargs.get("worktree_path") or ""
        return "ok"

    runtime.configure(provider=None, cwd=str(repo), subagent_runner=runner)

    out = agent_tool.run({
        "description": "isolated inspect",
        "agent_type": "explorer",
        "prompt": "inspect",
        "isolation": "worktree",
    })

    assert out == "ok"
    assert seen["worktree_path"]
    assert "codex-agent-" in seen["worktree_path"]


def test_spawn_agent_worktree_rejects_dirty_main_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    runtime.configure(provider=None, cwd=str(repo), subagent_runner=lambda *args, **kwargs: "unused")

    out = agent_tool.run({
        "description": "isolated inspect",
        "agent_type": "explorer",
        "prompt": "inspect",
        "isolation": "worktree",
    })

    assert "requires a clean git tree" in out


def test_agent_worktree_diff_and_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    seen: dict[str, str] = {}

    def runner(prompt, context=None, **kwargs):
        worktree_path = Path(kwargs["worktree_path"])
        seen["worktree_path"] = str(worktree_path)
        (worktree_path / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
        (worktree_path / "NEW.txt").write_text("new file content\n", encoding="utf-8")
        return "changed tracked file"

    runtime.configure(provider=None, cwd=str(repo), subagent_runner=runner)

    out = agent_tool.run({
        "description": "isolated edit",
        "agent_type": "explorer",
        "prompt": "edit",
        "isolation": "worktree",
    })
    task = agent_tasks.list_tasks()[0]

    assert out == "changed tracked file"
    rendered = agent_output_tool.run({"task_id": task.id, "include_diff": True})
    assert "changed_files:" in rendered
    assert "- README.md" in rendered
    assert "- NEW.txt" in rendered
    assert "+changed" in rendered
    assert "new file content" in rendered

    cleanup = cleanup_agent_tool.run({"task_id": task.id, "force": True, "forget": True})
    assert "removed worktree:" in cleanup
    assert "forgot agent task:" in cleanup
    assert not Path(seen["worktree_path"]).exists()
    assert agent_tasks.list_tasks() == []


def test_cleanup_agent_force_is_danger_classified():
    assert cleanup_agent_tool.classify({"task_id": "agent_1", "force": True}) == "danger"
    assert cleanup_agent_tool.classify({"task_id": "agent_1"}) == "safe"


def test_worktree_remove_refuses_unmanaged_path(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    outside = tmp_path / "outside"
    outside.mkdir()

    try:
        worktrees.remove(tmp_path, outside, force=True)
    except RuntimeError as exc:
        assert "unmanaged worktree path" in str(exc)
    else:
        raise AssertionError("unmanaged worktree removal should fail")


def test_background_agent_task_can_be_inspected(tmp_path):
    def runner(prompt, context=None, **kwargs):
        time.sleep(0.05)
        return f"finished {kwargs['agent_type']} {prompt}"

    runtime.configure(provider=None, cwd=str(tmp_path), subagent_runner=runner)

    out = agent_tool.run({
        "description": "background inspect",
        "agent_type": "explorer",
        "mode": "background",
        "prompt": "scan",
    })

    assert "started explorer agent" in out
    task = agent_tasks.list_tasks()[0]
    for _ in range(30):
        if agent_tasks.require(task.id).status.value == "completed":
            break
        time.sleep(0.02)
    rendered = agent_tasks.format_task(agent_tasks.require(task.id))
    assert "completed" in rendered
    assert "finished explorer scan" in rendered


def test_background_agent_stop_marks_cancelled_after_runner_returns(tmp_path):
    def runner(prompt, context=None, **kwargs):
        time.sleep(0.08)
        return "late output"

    runtime.configure(provider=None, cwd=str(tmp_path), subagent_runner=runner)
    agent_tool.run({
        "description": "background stop",
        "agent_type": "explorer",
        "mode": "background",
        "prompt": "scan",
    })
    task = agent_tasks.list_tasks()[0]

    agent_tasks.request_stop(task.id, "test")
    for _ in range(30):
        if agent_tasks.require(task.id).status.value == "cancelled":
            break
        time.sleep(0.02)

    assert agent_tasks.require(task.id).status.value == "cancelled"


class _DoneProcess:
    def poll(self):
        return 0


def test_background_cleanup_forgets_only_finished_jobs(tmp_path):
    background._JOBS.clear()
    finished = background.Job(
        "done",
        "echo done",
        str(tmp_path),
        tmp_path / "done.log",
        time.time() - 10,
        _DoneProcess(),
    )
    background._JOBS[finished.id] = finished

    removed = background.cleanup_finished(max_age_seconds=0)

    assert removed == ["done"]
    assert background.list_jobs() == []


def test_background_logs_are_redacted(monkeypatch, tmp_path):
    secret = "background-secret-12345"
    monkeypatch.setenv("CRYPT_BG_TOKEN", secret)
    runtime.configure(provider=None, cwd=str(tmp_path), subagent_runner=None)

    job = background.start(
        "python -c \"import os; print('API_TOKEN=' + os.environ['CRYPT_BG_TOKEN'])\"",
        cwd=str(tmp_path),
    )
    for _ in range(50):
        raw = job.output_path.read_text(encoding="utf-8", errors="replace")
        if job.process.poll() is not None and "[redacted]" in raw:
            break
        time.sleep(0.05)

    raw = job.output_path.read_text(encoding="utf-8", errors="replace")
    assert secret not in raw
    assert "API_TOKEN=[redacted]" in raw


def test_bash_spill_logs_are_redacted(monkeypatch, tmp_path):
    secret = "spill-secret-12345"
    monkeypatch.setenv("CRYPT_SPILL_TOKEN", secret)
    monkeypatch.setattr(bash_tool, "_SPILL_DIR", tmp_path)

    path = Path(bash_tool._write_spill(f"echo {secret}", f"API_TOKEN={secret}\n", ""))
    raw = path.read_text(encoding="utf-8")

    assert secret not in raw
    assert "API_TOKEN=[redacted]" in raw


def test_tool_policy_enforces_worker_write_scope(tmp_path):
    runtime.configure(provider=None, cwd=str(tmp_path), subagent_runner=None)
    worker = agent_registry.get_agent("worker")

    with runtime.subagent_context(
        agent_type="worker",
        allowed_tools=worker.allowed_tools,
        write_paths=["allowed"],
        task_id="agent_scope",
    ):
        allowed = tool_policy.preflight("write_file", {"path": "allowed/file.txt", "content": "x"})
        blocked = tool_policy.preflight("write_file", {"path": "other/file.txt", "content": "x"})

    assert allowed.action == tool_policy.ALLOW
    assert blocked.action == tool_policy.BLOCK
    assert "outside assigned scope" in blocked.reason


def test_tool_policy_warns_then_blocks_repeated_write_loop(tmp_path):
    runtime.configure(provider=None, cwd=str(tmp_path), subagent_runner=None)
    args = {"path": "artifact.html", "content": "<html></html>"}

    assert tool_policy.preflight("write_file", args).action == tool_policy.ALLOW
    tool_policy.after_tool("write_file", args, ok=True)
    assert tool_policy.preflight("write_file", args).action == tool_policy.WARN

    for i in range(2):
        loop_args = {"path": "artifact.html", "content": f"<html>{i}</html>"}
        assert tool_policy.preflight("write_file", loop_args).action == tool_policy.ALLOW
        tool_policy.after_tool("write_file", loop_args, ok=True)

    blocked = tool_policy.preflight("write_file", {"path": "artifact.html", "content": "<html>again</html>"})
    assert blocked.action == tool_policy.BLOCK
    assert "write loop" in blocked.reason


def test_tool_policy_blocks_third_identical_write(tmp_path):
    runtime.configure(provider=None, cwd=str(tmp_path), subagent_runner=None)
    args = {"path": "artifact.html", "content": "<html></html>"}

    assert tool_policy.preflight("write_file", args).action == tool_policy.ALLOW
    tool_policy.after_tool("write_file", args, ok=True)
    assert tool_policy.preflight("write_file", args).action == tool_policy.WARN
    tool_policy.after_tool("write_file", args, ok=True)

    blocked = tool_policy.preflight("write_file", args)

    assert blocked.action == tool_policy.BLOCK
    assert "identical write loop" in blocked.reason


def test_evidence_records_check_commands_as_verification():
    evidence.record_tool_result(
        "bash",
        {"command": "python -m pytest -q tests/test_production_runtime.py"},
        ok=True,
        output="1 passed",
    )

    assert evidence.has_passing_verification() is True
    assert evidence.latest_verifications()[-1].status == "PASS"


def test_final_claim_guard_appends_unverified_note():
    guarded, note = final_claims.guard_text("Done, implemented.")

    assert note
    assert "unverified" in guarded


def test_final_claim_guard_allows_verified_claim():
    evidence.record_verification(evidence.VerificationResult(status="PASS", commands=["python -m pytest -q"]))

    guarded, note = final_claims.guard_text("Done, implemented.")

    assert guarded == "Done, implemented."
    assert note == ""


def test_verifier_output_parser_extracts_verdict_commands_and_risk():
    result = verifiers.parse_verifier_output(
        "Command: python -m pytest -q\nFinding: one issue\nRisk: low\nVERDICT: FAIL",
        task_id="agent_1",
    )

    assert result.status == "FAIL"
    assert result.commands == ["python -m pytest -q"]
    assert result.findings == ["one issue"]
    assert result.risk == "low"
    assert result.task_id == "agent_1"


def test_ui_smoke_renders_core_transcript_blocks(monkeypatch):
    printed: list[object] = []
    monkeypatch.setattr(ui.console, "print", lambda obj=None, *args, **kwargs: printed.append(obj))

    ui.info("user submitted a request")
    ui.assistant_start()
    ui.assistant_chunk("assistant output")
    ui.assistant_end()
    ui.tool_call("read_file", "core/ui.py")
    ui.tool_result(True, "ok", title="READ_FILE OUTPUT")
    ui.subagent_start("explorer: inspect")
    ui.subagent_end(True, "explorer: inspect")

    assert len(printed) >= 5

