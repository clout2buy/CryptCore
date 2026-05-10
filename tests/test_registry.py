"""Registry dispatch — permission integration, classify hooks, missing args."""
from __future__ import annotations

from core import runtime
from tools import registry
from tools.types import Tool


def _stub_tool(
    name: str = "stub",
    permission: str = "auto",
    classify=None,
    validate=None,
    runner=lambda args: f"ran {args}",
    parallel_safe: bool = False,
) -> Tool:
    return Tool(
        name=name,
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission=permission,
        run=runner,
        classify=classify,
        validate=validate,
        parallel_safe=parallel_safe,
        summary=lambda args: str(args.get("x", "")),
    )


def test_unknown_tool_returns_error():
    ok, msg = registry.dispatch("nonexistent_tool", {}, render=False)
    assert ok is False
    assert "unknown" in msg


def test_missing_required_arg(monkeypatch):
    tool = _stub_tool(permission="auto")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, msg = registry.dispatch(tool.name, {}, render=False)
    assert ok is False
    assert "missing required input" in msg


def test_non_object_tool_input_is_rejected(monkeypatch):
    tool = _stub_tool(permission="auto")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, msg = registry.dispatch(tool.name, ["not", "an", "object"], render=False)
    assert ok is False
    assert "expected JSON object" in msg


def test_schema_validation_rejects_wrong_type(monkeypatch):
    tool = _stub_tool(permission="auto")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, msg = registry.dispatch(tool.name, {"x": 123}, render=False)
    assert ok is False
    assert "schema validation failed" in msg
    assert "x: expected string" in msg


def test_required_string_may_be_empty(monkeypatch):
    tool = _stub_tool(permission="auto")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, msg = registry.dispatch(tool.name, {"x": ""}, render=False)
    assert ok is True
    assert "ran" in msg


def test_schema_validation_checks_nested_enum(monkeypatch):
    tool = Tool(
        name="nested",
        description="nested",
        schema={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string", "enum": ["pending", "done"]},
                        },
                        "required": ["status"],
                    },
                },
            },
            "required": ["items"],
        },
        permission="auto",
        run=lambda args: "ran",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, msg = registry.dispatch(tool.name, {"items": [{"status": "doing"}]}, render=False)
    assert ok is False
    assert "items[0].status" in msg
    assert "expected one of" in msg


def test_semantic_validation_runs_before_approval(monkeypatch):
    tool = _stub_tool(
        permission="ask",
        validate=lambda args: ["x cannot be bad"] if args.get("x") == "bad" else [],
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    ok, msg = registry.dispatch(tool.name, {"x": "bad"}, render=False)

    assert ok is False
    assert "x cannot be bad" in msg


def test_empty_edit_validation_gives_recovery_hint(monkeypatch):
    tool = Tool(
        name="edit_file",
        description="edit",
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "edits": {"type": "array"},
            },
            "required": ["path"],
        },
        permission="ask",
        run=lambda args: "ran",
        validate=lambda args: ["edits: expected a non-empty array of {old, new} objects"],
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    ok, msg = registry.dispatch(tool.name, {"path": "x.py", "edits": []}, render=False)

    assert ok is False
    assert "Empty edits are never valid" in msg
    assert "read_file" in msg


def test_auto_tool_runs_without_prompt(monkeypatch):
    tool = _stub_tool(permission="auto")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, output = registry.dispatch(tool.name, {"x": "hi"}, render=False)
    assert ok is True
    assert "ran" in output


def test_subagent_allowlist_is_enforced_at_dispatch(monkeypatch):
    tool = _stub_tool(permission="auto")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    with runtime.subagent_context(agent_type="explorer", allowed_tools={"read_file"}, task_id="agent_1"):
        ok, output = registry.dispatch(tool.name, {"x": "hi"}, render=False)

    assert ok is False
    assert "not allowed for this subagent" in output


def test_ask_tool_without_auto_approval_blocks_when_non_interactive(monkeypatch):
    """Non-rendered ask-tools must fail cleanly instead of calling input()."""
    tool = _stub_tool(permission="ask")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, output = registry.dispatch(tool.name, {"x": "hi"}, render=False)
    assert ok is False
    assert "approval required" in output


def test_auto_work_runs_common_ask_tools_without_prompt(monkeypatch):
    previous = runtime.approval_mode()
    runtime.set_approval_mode(runtime.APPROVAL_EDITS)
    try:
        tool = _stub_tool(name="web_search", permission="ask")
        monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

        ok, output = registry.dispatch(tool.name, {"x": "hi"}, render=False)

        assert ok is True
        assert "ran" in output
    finally:
        runtime.set_approval_mode(previous)


def test_auto_work_does_not_expand_subagent_ask_permissions(monkeypatch):
    previous = runtime.approval_mode()
    runtime.set_approval_mode(runtime.APPROVAL_EDITS)
    try:
        tool = _stub_tool(name="web_search", permission="ask")
        monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

        with runtime.subagent_context(agent_type="explorer", allowed_tools={"web_search"}, task_id="agent_1"):
            ok, output = registry.dispatch(tool.name, {"x": "hi"}, render=False)

        assert ok is False
        assert "interactive tool call unavailable in non-interactive subagent" in output
    finally:
        runtime.set_approval_mode(previous)


def test_subagent_ask_tool_uses_approval_handler_when_available(monkeypatch):
    previous = runtime.approval_mode()
    runtime.set_approval_mode(runtime.APPROVAL_EDITS)
    calls: list[dict] = []
    try:
        tool = _stub_tool(name="web_search", permission="ask")
        monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

        def approve(**kwargs):
            calls.append(kwargs)
            return True, ""

        with runtime.approval_handler(approve):
            with runtime.subagent_context(agent_type="explorer", allowed_tools={"web_search"}, task_id="agent_1"):
                ok, output = registry.dispatch(tool.name, {"x": "hi"}, render=False)

        assert ok is True
        assert "ran" in output
        assert calls[0]["tool_name"] == "web_search"
        assert calls[0]["summary"] == "hi"
    finally:
        runtime.set_approval_mode(previous)


def test_yolo_all_allows_subagent_ask_tools(monkeypatch):
    previous = runtime.approval_mode()
    runtime.set_approval_mode(runtime.APPROVAL_ALL)
    try:
        tool = _stub_tool(name="web_search", permission="ask")
        monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

        with runtime.subagent_context(agent_type="explorer", allowed_tools={"web_search"}, task_id="agent_1"):
            ok, output = registry.dispatch(tool.name, {"x": "hi"}, render=False)

        assert ok is True
        assert "ran" in output
    finally:
        runtime.set_approval_mode(previous)


def test_noninteractive_manual_uses_approval_handler(monkeypatch):
    previous = runtime.approval_mode()
    runtime.set_approval_mode(runtime.APPROVAL_NORMAL)
    calls: list[dict] = []
    try:
        tool = _stub_tool(permission="ask")
        monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

        def approve(**kwargs):
            calls.append(kwargs)
            return True, ""

        with runtime.approval_handler(approve):
            ok, output = registry.dispatch(tool.name, {"x": "hi"}, render=False)

        assert ok is True
        assert "ran" in output
        assert calls[0]["tool_name"] == "stub"
        assert calls[0]["summary"] == "hi"
    finally:
        runtime.set_approval_mode(previous)


def test_classify_safe_skips_prompt(monkeypatch):
    tool = _stub_tool(permission="ask", classify=lambda args: "safe")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, output = registry.dispatch(tool.name, {"x": "hi"}, render=False)
    assert ok is True


def test_classify_danger_blocks_subagent(monkeypatch):
    tool = _stub_tool(permission="auto", classify=lambda args: "danger")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, output = registry.dispatch(tool.name, {"x": "hi"}, render=False)
    assert ok is False
    assert "approval required" in output


def test_permissions_deny_short_circuits(monkeypatch, tmp_path):
    """A deny rule must reject the call even before classify runs."""
    from core import permissions
    pf = tmp_path / "permissions.json"
    pf.write_text('{"deny": ["stub:hi"]}')
    monkeypatch.setattr(permissions, "PERMISSIONS_PATH", pf)
    monkeypatch.setattr(permissions, "_CACHE", None)
    monkeypatch.setattr(permissions, "_CACHE_MTIME", None)

    tool = _stub_tool(permission="auto")  # would normally run
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, msg = registry.dispatch(tool.name, {"x": "hi"}, render=False)
    assert ok is False
    assert "permissions rule" in msg


def test_run_exception_surfaces_as_failure(monkeypatch):
    def bad_run(args):
        raise RuntimeError("boom")
    tool = _stub_tool(permission="auto", runner=bad_run)
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    ok, msg = registry.dispatch(tool.name, {"x": "hi"}, render=False)
    assert ok is False
    assert "RuntimeError" in msg
    assert "boom" in msg


def test_edit_failure_includes_specific_recovery_hint(monkeypatch):
    def bad_run(args):
        raise ValueError("edit 1: no match for 'old text'")

    tool = Tool(
        name="edit_file",
        description="edit",
        schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        permission="auto",
        run=bad_run,
        summary=lambda args: str(args.get("path", "")),
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    ok, msg = registry.dispatch(tool.name, {"path": "app.py"}, render=False)

    assert ok is False
    assert "Recovery:" in msg
    assert "read_file" in msg
    assert "exact current source" in msg


# ─── lifecycle UI integration ───────────────────────────────────────────


class _LifecycleSpy:
    """Captures every UI lifecycle call made during dispatch."""

    def __init__(self) -> None:
        self.events: list[tuple[str, ...]] = []

    def install(self, monkeypatch):
        from core import ui

        monkeypatch.setattr(ui, "tool_begin", lambda tid, name, summary:
                            self.events.append(("begin", tid, name, summary)))
        monkeypatch.setattr(ui, "tool_set_state", lambda tid, state, detail="":
                            self.events.append(("state", tid, state, detail)))
        monkeypatch.setattr(ui, "tool_end", lambda tid, ok, output="":
                            self.events.append(("end", tid, ok, output)))
        # Quiet-mode legacy paths shouldn't fire when tool_use_id is set, but
        # spy on them so a regression here shows up clearly.
        monkeypatch.setattr(ui, "tool_call", lambda name, summary:
                            self.events.append(("legacy_call", name, summary)))
        monkeypatch.setattr(ui, "tool_result", lambda ok, output="":
                            self.events.append(("legacy_result", ok, output)))
        monkeypatch.setattr(ui, "activity", lambda label: None)
        monkeypatch.setattr(ui, "info", lambda label: None)


def test_dispatch_with_tool_use_id_emits_begin_running_end(monkeypatch):
    spy = _LifecycleSpy()
    spy.install(monkeypatch)
    tool = _stub_tool(permission="auto")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    ok, _ = registry.dispatch(tool.name, {"x": "hi"}, render=True, tool_use_id="call_1")

    assert ok is True
    kinds = [e[0] for e in spy.events]
    assert kinds == ["begin", "state", "end"]
    assert spy.events[0] == ("begin", "call_1", "stub", "hi")
    assert spy.events[1] == ("state", "call_1", "running", "")
    end = spy.events[2]
    assert end[0] == "end" and end[1] == "call_1" and end[2] is True


def test_dispatch_validation_failure_uses_lifecycle_path(monkeypatch):
    spy = _LifecycleSpy()
    spy.install(monkeypatch)
    tool = _stub_tool(permission="auto")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    ok, msg = registry.dispatch(tool.name, {"x": 123}, render=True, tool_use_id="call_1")

    assert ok is False
    assert "schema validation failed" in msg
    # Begin then end err — no legacy calls, no running state.
    kinds = [e[0] for e in spy.events]
    assert kinds == ["begin", "end"]
    assert spy.events[1][2] is False  # ok=False


def test_dispatch_non_object_input_uses_lifecycle_path(monkeypatch):
    spy = _LifecycleSpy()
    spy.install(monkeypatch)
    tool = _stub_tool(permission="auto")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    ok, _ = registry.dispatch(tool.name, ["not", "object"], render=True, tool_use_id="call_1")

    assert ok is False
    kinds = [e[0] for e in spy.events]
    assert kinds == ["begin", "end"]
    # Header summary should call out the bad input.
    assert spy.events[0][3] == "<invalid input>"


def test_dispatch_run_exception_uses_lifecycle_path(monkeypatch):
    spy = _LifecycleSpy()
    spy.install(monkeypatch)

    def bad_run(args):
        raise RuntimeError("boom")
    tool = _stub_tool(permission="auto", runner=bad_run)
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    ok, msg = registry.dispatch(tool.name, {"x": "hi"}, render=True, tool_use_id="call_1")

    assert ok is False
    assert "RuntimeError" in msg and "boom" in msg
    # begin → running → end (err) — exception didn't skip the running phase.
    kinds = [e[0] for e in spy.events]
    assert kinds == ["begin", "state", "end"]
    assert spy.events[1] == ("state", "call_1", "running", "")
    assert spy.events[2][2] is False


def test_dispatch_without_tool_use_id_uses_legacy_path(monkeypatch):
    """Backward-compat: no tool_use_id → tool_call/tool_result, no lifecycle."""
    spy = _LifecycleSpy()
    spy.install(monkeypatch)
    tool = _stub_tool(permission="auto")
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    ok, _ = registry.dispatch(tool.name, {"x": "hi"}, render=True)

    assert ok is True
    kinds = [e[0] for e in spy.events]
    # Legacy: tool_call (start) then tool_result (end). No lifecycle calls.
    assert "begin" not in kinds
    assert "state" not in kinds
    assert "end" not in kinds
    assert "legacy_call" in kinds
    assert "legacy_result" in kinds
