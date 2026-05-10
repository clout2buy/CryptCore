from __future__ import annotations

import threading
import time

from core import artifacts, loop, runtime
import pytest

from core.api import (
    ThinkingDelta,
    TextDelta,
    ToolUseProgress,
    ToolUseReady,
    TurnEnd,
    _finalized_assistant_message,
    _process_event,
)
from tools import registry
from tools.types import Tool


class _FakeProvider:
    name = "fake"
    model = "fake-model"
    is_oauth = False

    def stream_turn(self, messages, tools, system):
        yield TextDelta("I'll do that.")
        yield TurnEnd(
            stop_reason="tool_use",
            message={
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll do that."},
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "read_file",
                        "input": {"path": "README.md"},
                    },
                ],
            },
        )


def test_stream_one_turn_cuts_over_to_ready_tool(workspace):
    provider = _FakeProvider()
    runtime.configure(provider, str(workspace), session=None)

    end = loop._stream_one_turn(
        provider,
        messages=[],
        tools=[],
        loader=loop._SilentLoader(),
        render=False,
    )

    assert end.stop_reason == "tool_use"
    assert end.message["content"][1]["name"] == "read_file"
    assert end.message["content"][1]["input"] == {"path": "README.md"}


def test_stream_one_turn_emits_text_deltas_to_event_sink(workspace):
    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def stream_turn(self, messages, tools, system):
            yield TextDelta("hello")
            yield TextDelta(" world")
            yield TurnEnd(
                stop_reason="end_turn",
                message={"role": "assistant", "content": [{"type": "text", "text": "hello world"}]},
            )

    events: list[dict] = []
    provider = Provider()
    runtime.configure(provider, str(workspace), session=None)

    loop._stream_one_turn(
        provider,
        messages=[{"role": "user", "content": "say hi"}],
        tools=[],
        loader=loop._SilentLoader(),
        render=False,
        event_sink=events.append,
    )

    assert [event["text"] for event in events if event["event"] == "assistantDelta"] == ["hello", " world"]


def test_stream_one_turn_emits_thinking_deltas_when_enabled(workspace):
    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def stream_turn(self, messages, tools, system):
            yield ThinkingDelta("plan")
            yield TurnEnd(
                stop_reason="end_turn",
                message={"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            )

    events: list[dict] = []
    provider = Provider()
    previous = runtime.show_thinking()
    runtime.configure(provider, str(workspace), session=None)
    runtime.set_show_thinking(True)
    try:
        loop._stream_one_turn(
            provider,
            messages=[{"role": "user", "content": "think"}],
            tools=[],
            loader=loop._SilentLoader(),
            render=False,
            event_sink=events.append,
        )
    finally:
        runtime.set_show_thinking(previous)

    assert [event["text"] for event in events if event["event"] == "thinkingDelta"] == ["plan"]


def test_dispatch_tool_uses_emits_live_tool_events(monkeypatch, workspace):
    class Provider:
        is_oauth = False

    tool = Tool(
        name="event_stub",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=lambda args: f"ran {args['x']}",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    runtime.configure(Provider(), str(workspace), session=None)
    events: list[dict] = []
    assistant_msg = {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "call_event", "name": "event_stub", "input": {"x": "now"}},
        ],
    }
    messages = [assistant_msg]

    loop._dispatch_tool_uses(
        Provider(),
        assistant_msg,
        messages,
        record=False,
        render=False,
        event_sink=events.append,
    )

    assert [event["event"] for event in events] == ["toolStarted", "toolResult"]
    assert events[0]["callId"] == "call_event"
    assert events[1]["ok"] is True
    assert events[1]["text"] == "ran now"


def test_dispatch_tool_uses_skips_batch_after_validation_failure(monkeypatch, workspace):
    class Provider:
        is_oauth = False

    ran: list[str] = []
    first = Tool(
        name="invalid_first",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=lambda args: "should not run",
    )
    second = Tool(
        name="second_after_invalid",
        description="stub",
        schema={"type": "object", "properties": {}, "required": []},
        permission="auto",
        run=lambda args: ran.append("second") or "ran",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, first.name, first)
    monkeypatch.setitem(registry.REGISTRY._tools, second.name, second)
    runtime.configure(Provider(), str(workspace), session=None)
    assistant_msg = {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "call_bad", "name": first.name, "input": {"x": 123}},
            {"type": "tool_use", "id": "call_second", "name": second.name, "input": {}},
        ],
    }
    messages = [assistant_msg]

    loop._dispatch_tool_uses(Provider(), assistant_msg, messages, record=False, render=False)

    assert ran == []
    results = messages[-1]["content"]
    assert results[0]["is_error"] is True
    assert "schema validation failed" in results[0]["content"]
    assert results[1]["is_error"] is True
    assert "skipped: previous tool failed" in results[1]["content"]


def test_anthropic_block_stop_emits_tool_ready_before_full_message():
    content_blocks = []
    usage = {"input_tokens": 10, "output_tokens": 3}

    list(_process_event(
        "content_block_start",
        {
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "read_file",
            },
        },
        content_blocks,
        usage,
    ))
    list(_process_event(
        "content_block_delta",
        {
            "index": 0,
            "delta": {
                "type": "input_json_delta",
                "partial_json": '{"path":"README.md"}',
            },
        },
        content_blocks,
        usage,
    ))

    events = list(_process_event(
        "content_block_stop",
        {"index": 0},
        content_blocks,
        usage,
    ))

    ready = [event for event in events if isinstance(event, ToolUseReady)]
    assert len(ready) == 1
    assert ready[0].message["content"][0]["input"] == {"path": "README.md"}
    assert _finalized_assistant_message(content_blocks)["content"] == [
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "read_file",
            "input": {"path": "README.md"},
        }
    ]


def test_anthropic_multiple_tool_blocks_survive_until_final_message():
    content_blocks = []
    usage = {"input_tokens": 10, "output_tokens": 3}

    for idx, tool_id, path in [
        (0, "toolu_1", "a.py"),
        (1, "toolu_2", "b.py"),
    ]:
        list(_process_event(
            "content_block_start",
            {
                "index": idx,
                "content_block": {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "read_file",
                },
            },
            content_blocks,
            usage,
        ))
        list(_process_event(
            "content_block_delta",
            {
                "index": idx,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": f'{{"path":"{path}"}}',
                },
            },
            content_blocks,
            usage,
        ))
        events = list(_process_event(
            "content_block_stop",
            {"index": idx},
            content_blocks,
            usage,
        ))
        ready = [event for event in events if isinstance(event, ToolUseReady)]
        assert len(ready) == 1
        assert ready[0].message["content"][-1]["input"] == {"path": path}

    msg = _finalized_assistant_message(content_blocks)
    assert [b["id"] for b in msg["content"]] == ["toolu_1", "toolu_2"]
    assert [b["input"]["path"] for b in msg["content"]] == ["a.py", "b.py"]


def test_multi_tool_assistant_message_uses_parallel_dispatch(monkeypatch):
    class Provider:
        is_oauth = False

    calls: list[list[str]] = []

    def fake_parallel(blocks, *, render, event_sink=None):
        calls.append([block["id"] for block in blocks])
        return [
            {
                "type": "tool_result",
                "tool_use_id": block["id"],
                "content": "ok",
                "is_error": False,
            }
            for block in blocks
        ]

    tool = Tool(
        name="parallel_stub",
        description="stub",
        schema={"type": "object", "properties": {}, "required": []},
        permission="auto",
        run=lambda args: "ok",
        parallel_safe=True,
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    monkeypatch.setattr(loop, "_dispatch_parallel", fake_parallel)

    assistant_msg = {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "call_1", "name": "parallel_stub", "input": {}},
            {"type": "tool_use", "id": "call_2", "name": "parallel_stub", "input": {}},
        ],
    }
    messages = [assistant_msg]

    loop._dispatch_tool_uses(Provider(), assistant_msg, messages, record=False, render=False)

    assert calls == [["call_1", "call_2"]]
    assert [b["tool_use_id"] for b in messages[-1]["content"]] == ["call_1", "call_2"]


def test_parallel_dispatch_preserves_approval_handler(monkeypatch):
    previous = runtime.approval_mode()
    runtime.set_approval_mode(runtime.APPROVAL_NORMAL)
    approvals: list[str] = []
    try:
        tool = Tool(
            name="parallel_approval_stub",
            description="stub",
            schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
            permission="ask",
            run=lambda args: f"ok {args['x']}",
            summary=lambda args: args["x"],
            parallel_safe=True,
        )
        monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
        blocks = [
            {"type": "tool_use", "id": "call_1", "name": tool.name, "input": {"x": "one"}},
            {"type": "tool_use", "id": "call_2", "name": tool.name, "input": {"x": "two"}},
        ]

        def approve(**kwargs):
            approvals.append(kwargs["summary"])
            return True, ""

        with runtime.approval_handler(approve):
            results = loop._dispatch_parallel(blocks, render=False)

        assert [item["is_error"] for item in results] == [False, False]
        assert [item["content"] for item in results] == ["ok one", "ok two"]
        assert sorted(approvals) == ["one", "two"]
    finally:
        runtime.set_approval_mode(previous)


def test_streaming_executor_preserves_approval_handler(monkeypatch):
    previous = runtime.approval_mode()
    runtime.set_approval_mode(runtime.APPROVAL_NORMAL)
    approvals: list[str] = []
    try:
        tool = Tool(
            name="read_file",
            description="stub",
            schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            permission="ask",
            run=lambda args: f"read {args['path']}",
            classify=lambda args: "ask",
            summary=lambda args: args["path"],
        )
        monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
        executor = loop._StreamingToolExecutor(render=False)
        block = {"type": "tool_use", "id": "call_stream", "name": "read_file", "input": {"path": "outside.txt"}}

        def approve(**kwargs):
            approvals.append(kwargs["summary"])
            return True, ""

        with runtime.approval_handler(approve):
            executor.add(block)
            results = executor.finish()

        assert results == [{
            "type": "tool_result",
            "tool_use_id": "call_stream",
            "content": "read outside.txt",
            "is_error": False,
        }]
        assert approvals == ["outside.txt"]
    finally:
        runtime.set_approval_mode(previous)


def test_streaming_tool_executor_starts_tool_before_message_stop(monkeypatch, workspace):
    started = threading.Event()
    provider_saw_started: list[bool] = []
    calls: list[str] = []

    def run(args):
        calls.append(args["x"])
        started.set()
        time.sleep(0.05)
        return "streamed ok"

    tool = Tool(
        name="stream_stub",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=run,
        classify=lambda args: "safe",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def stream_turn(self, messages, tools, system):
            block = {
                "type": "tool_use",
                "id": "call_stream",
                "name": "stream_stub",
                "input": {"x": "now"},
            }
            message = {"role": "assistant", "content": [block]}
            yield ToolUseReady(message=message, tool=block)
            provider_saw_started.append(started.wait(1))
            yield TurnEnd(stop_reason="tool_use", message=message)

    runtime.configure(Provider(), str(workspace), session=None)

    end = loop._stream_one_turn(
        Provider(),
        messages=[{"role": "user", "content": "use tool"}],
        tools=[],
        loader=loop._SilentLoader(),
        render=False,
    )

    assert provider_saw_started == [True]
    assert calls == ["now"]
    assert end.tool_results == [{
        "type": "tool_result",
        "tool_use_id": "call_stream",
        "content": "streamed ok",
        "is_error": False,
    }]


def test_streaming_tool_completion_is_drained_during_provider_stream(monkeypatch, workspace):
    finished = threading.Event()
    visible_end = threading.Event()
    provider_saw_visible_end: list[bool] = []

    def run(args):
        finished.set()
        return "streamed ok"

    tool = Tool(
        name="stream_drain",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=run,
        classify=lambda args: "safe",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    monkeypatch.setattr(loop.ui, "activity", lambda label: None)
    monkeypatch.setattr(loop.ui, "stream_delta", lambda kind, text: None)
    monkeypatch.setattr(loop.ui, "stream_clear", lambda: None)
    monkeypatch.setattr(loop.ui, "tool_progress_clear", lambda: None)
    monkeypatch.setattr(loop.ui, "tool_begin", lambda tool_id, name, summary: None)
    monkeypatch.setattr(loop.ui, "tool_set_state", lambda tool_id, state, detail="": None)
    monkeypatch.setattr(loop.ui, "tool_end", lambda tool_id, ok, output="": visible_end.set())
    monkeypatch.setattr(loop.ui, "assistant_start", lambda: None)
    monkeypatch.setattr(loop.ui, "assistant_chunk", lambda text: None)
    monkeypatch.setattr(loop.ui, "assistant_end", lambda: None)

    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = True

        def stream_turn(self, messages, tools, system):
            block = {
                "type": "tool_use",
                "id": "call_drain",
                "name": "stream_drain",
                "input": {"x": "now"},
            }
            message = {"role": "assistant", "content": [block]}
            yield ToolUseReady(message=message, tool=block)
            assert finished.wait(1)
            yield TextDelta("still streaming")
            provider_saw_visible_end.append(visible_end.is_set())
            yield TurnEnd(stop_reason="tool_use", message=message)

    runtime.configure(Provider(), str(workspace), session=None)

    loop._stream_one_turn(
        Provider(),
        messages=[{"role": "user", "content": "use tool"}],
        tools=[],
        loader=loop._SilentLoader(),
        render=True,
    )

    assert provider_saw_visible_end == [True]


def test_stream_error_after_tool_ready_preserves_tool_result(monkeypatch, workspace):
    calls: list[str] = []

    def run(args):
        calls.append(args["x"])
        return "streamed ok"

    tool = Tool(
        name="stream_recover",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=run,
        classify=lambda args: "safe",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def stream_turn(self, messages, tools, system):
            block = {
                "type": "tool_use",
                "id": "call_recover",
                "name": "stream_recover",
                "input": {"x": "once"},
            }
            message = {"role": "assistant", "content": [block]}
            yield ToolUseReady(message=message, tool=block)
            raise TimeoutError("stream dropped")

    runtime.configure(Provider(), str(workspace), session=None)

    end = loop._stream_one_turn(
        Provider(),
        messages=[{"role": "user", "content": "use tool"}],
        tools=[],
        loader=loop._SilentLoader(),
        render=False,
    )

    assert end.stop_reason == "tool_use"
    assert calls == ["once"]
    assert end.tool_results == [{
        "type": "tool_result",
        "tool_use_id": "call_recover",
        "content": "streamed ok",
        "is_error": False,
    }]


def test_stream_gap_tracing_records_long_event_gap(monkeypatch, workspace):
    emitted: list[tuple[str, dict]] = []

    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def stream_turn(self, messages, tools, system):
            yield TextDelta("a")
            yield TextDelta("b")
            yield TurnEnd(
                stop_reason="end_turn",
                message={"role": "assistant", "content": [{"type": "text", "text": "ab"}]},
            )

    times = iter([0.0, 0.1, 35.5, 35.6])
    monkeypatch.setenv("CRYPT_STREAM_GAP_TRACE_SECONDS", "30")
    monkeypatch.setattr(loop.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(loop.tracing, "emit", lambda event, **fields: emitted.append((event, fields)))
    runtime.configure(Provider(), str(workspace), session=None)

    loop._stream_one_turn(
        Provider(),
        messages=[{"role": "user", "content": "say ab"}],
        tools=[],
        loader=loop._SilentLoader(),
        render=False,
    )

    assert emitted[0][0] == "stream_first_event"
    gaps = [fields for event, fields in emitted if event == "stream_gap"]
    assert len(gaps) == 1
    assert gaps[0]["gap_seconds"] == 35.4
    summaries = [fields for event, fields in emitted if event == "stream_gap_summary"]
    assert summaries == [{"gap_count": 1, "total_gap_seconds": 35.4}]


def test_artifact_fast_lane_hides_task_management_before_first_write(workspace):
    runtime.configure(_FakeProvider(), str(workspace), session=None)
    messages = [{"role": "user", "content": "build a single-file animated html and open it"}]

    offered = {tool["name"] for tool in loop._tools_for_turn(messages, is_subagent=False)}

    assert "write_file" in offered
    assert "edit_file" in offered
    assert "open_file" in offered
    assert "todos" not in offered
    assert "present_plan" not in offered
    assert "ask_user" not in offered


def test_artifact_fast_lane_releases_after_file_write(workspace):
    runtime.configure(_FakeProvider(), str(workspace), session=None)
    messages = [
        {"role": "user", "content": "build a single-file animated html and open it"},
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "write_1",
                "name": "write_file",
                "input": {"path": "demo.html", "content": "<html></html>"},
            }],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "write_1",
                "content": "created demo.html",
                "is_error": False,
            }],
        },
    ]

    offered = {tool["name"] for tool in loop._tools_for_turn(messages, is_subagent=False)}

    assert "todos" in offered
    assert "present_plan" in offered


def test_artifact_fast_lane_does_not_leak_to_followup_prompt(workspace):
    runtime.configure(_FakeProvider(), str(workspace), session=None)
    messages = [
        {"role": "user", "content": "build a single-file animated html and open it"},
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "write_1",
                "name": "write_file",
                "input": {"path": "demo.html", "content": "<html></html>"},
            }],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "write_1",
                "content": "created demo.html",
                "is_error": False,
            }],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Done. demo.html is open."}],
        },
        {"role": "user", "content": "nicely done"},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Thanks."}],
        },
        {"role": "user", "content": "f"},
    ]

    offered = {tool["name"] for tool in loop._tools_for_turn(messages, is_subagent=False)}

    assert not artifacts.creation_requested(messages)
    assert "todos" in offered
    assert "present_plan" in offered


def test_artifact_fast_lane_survives_harness_correction(workspace):
    runtime.configure(_FakeProvider(), str(workspace), session=None)
    messages = [{"role": "user", "content": "build a single-file animated html and open it"}]
    messages.append(artifacts.empty_retry_message(messages))

    offered = {tool["name"] for tool in loop._tools_for_turn(messages, is_subagent=False)}
    guidance = artifacts.fast_lane_system_guidance(messages)

    assert artifacts.creation_requested(messages)
    assert "build a single-file animated html and open it" in guidance
    assert "previous response ended empty" not in guidance
    assert "todos" not in offered
    assert "present_plan" not in offered


def test_run_until_done_uses_streamed_tool_result_once(monkeypatch, workspace):
    calls: list[str] = []

    def run(args):
        calls.append(args["x"])
        return "streamed ok"

    tool = Tool(
        name="stream_once",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=run,
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def __init__(self):
            self.turns = 0

        def stream_turn(self, messages, tools, system):
            self.turns += 1
            if self.turns == 1:
                block = {
                    "type": "tool_use",
                    "id": "call_once",
                    "name": "stream_once",
                    "input": {"x": "once"},
                }
                message = {"role": "assistant", "content": [block]}
                yield ToolUseReady(message=message, tool=block)
                yield TurnEnd(stop_reason="tool_use", message=message)
                return
            assert any(
                block.get("tool_use_id") == "call_once"
                for msg in messages
                for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
                if isinstance(block, dict)
            )
            yield TurnEnd(
                stop_reason="end_turn",
                message={"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            )

    provider = Provider()
    runtime.configure(provider, str(workspace), session=None)
    messages = [{"role": "user", "content": "use tool once"}]

    loop._run_until_done(provider, messages, 0, 0, render=False)

    assert provider.turns == 2
    assert calls == ["once"]
    assert sum(
        1
        for msg in messages
        for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
        if isinstance(block, dict) and block.get("tool_use_id") == "call_once"
    ) == 1


def test_streaming_tool_executor_keeps_foreground_tools_until_turn_end(monkeypatch, workspace):
    started = threading.Event()
    provider_saw_started: list[bool] = []

    tool = Tool(
        name="ask_user",
        description="stub",
        schema={"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
        permission="auto",
        run=lambda args: started.set() or "answered",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def stream_turn(self, messages, tools, system):
            block = {
                "type": "tool_use",
                "id": "call_ask",
                "name": "ask_user",
                "input": {"question": "Continue?"},
            }
            message = {"role": "assistant", "content": [block]}
            yield ToolUseReady(message=message, tool=block)
            provider_saw_started.append(started.is_set())
            yield TurnEnd(stop_reason="tool_use", message=message)

    runtime.configure(Provider(), str(workspace), session=None)

    end = loop._stream_one_turn(
        Provider(),
        messages=[{"role": "user", "content": "ask me"}],
        tools=[],
        loader=loop._SilentLoader(),
        render=False,
    )

    assert provider_saw_started == [False]
    assert started.is_set()
    assert end.tool_results == [{
        "type": "tool_result",
        "tool_use_id": "call_ask",
        "content": "answered",
        "is_error": False,
    }]


def test_anthropic_json_delta_emits_tool_progress():
    content_blocks = []
    usage = {"input_tokens": 0, "output_tokens": 0}

    start_events = list(_process_event(
        "content_block_start",
        {
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "write_file",
            },
        },
        content_blocks,
        usage,
    ))
    delta_events = list(_process_event(
        "content_block_delta",
        {
            "index": 0,
            "delta": {
                "type": "input_json_delta",
                "partial_json": '{"path":"demo.html"',
            },
        },
        content_blocks,
        usage,
    ))

    progress = [event for event in start_events + delta_events if isinstance(event, ToolUseProgress)]
    assert len(progress) == 2
    assert progress[-1].name == "write_file"
    assert progress[-1].call_id == "toolu_1"
    assert progress[-1].argument_chars == len('{"path":"demo.html"')
    assert progress[-1].partial_json == '{"path":"demo.html"'


def test_tool_progress_detail_surfaces_partial_write_file():
    event = ToolUseProgress(
        name="write_file",
        call_id="toolu_1",
        argument_chars=62,
        partial_json='{"path":"demo.html","content":"<html>\\n<body>hi',
    )

    detail = loop._tool_progress_detail(event)

    assert "demo.html" in detail
    assert "2 line(s)" in detail
    assert "chars" in detail


def test_tool_progress_preview_surfaces_tail_of_partial_file():
    event = ToolUseProgress(
        name="write_file",
        call_id="toolu_1",
        argument_chars=120,
        partial_json='{"path":"demo.html","content":"<html>\\n<body>\\n<canvas id=\\"c\\">\\n<script>tick()',
    )

    preview = loop._tool_progress_preview(event)

    assert preview[-2:] == ['<canvas id="c">', "<script>tick()"]


def test_hidden_reasoning_stall_aborts(monkeypatch, workspace):
    class SlowThinkingProvider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def stream_turn(self, messages, tools, system):
            yield ThinkingDelta("still thinking")
            yield ThinkingDelta("still thinking")

    times = iter([0.0, 0.0, 46.0])
    monkeypatch.setenv("CRYPT_REASONING_STALL_SECONDS", "45")
    monkeypatch.setenv("CRYPT_ARTIFACT_REASONING_STALL_SECONDS", "45")
    monkeypatch.setattr(loop.time, "monotonic", lambda: next(times))
    runtime.configure(SlowThinkingProvider(), str(workspace), session=None)
    runtime.set_show_thinking(False)

    with pytest.raises(RuntimeError, match="too long in reasoning"):
        loop._stream_one_turn(
            SlowThinkingProvider(),
            messages=[{"role": "user", "content": "make a file"}],
            tools=[],
            loader=loop._SilentLoader(),
            render=True,
        )


def test_artifact_reasoning_stall_retries_with_tool_instruction(monkeypatch, workspace):
    class StallThenToolProvider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def __init__(self) -> None:
            self.calls = 0
            self.seen_messages: list[list[dict]] = []

        def stream_turn(self, messages, tools, system):
            self.calls += 1
            self.seen_messages.append(list(messages))
            if self.calls == 1:
                yield ThinkingDelta("still thinking")
                yield ThinkingDelta("still thinking")
                return
            if self.calls == 2:
                assert any(
                    "spent too long in hidden reasoning" in block.get("text", "")
                    for msg in messages
                    for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
                    if isinstance(block, dict)
                )
                yield TurnEnd(
                    stop_reason="tool_use",
                    message={
                        "role": "assistant",
                        "content": [{
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "stub",
                            "input": {"x": "ok"},
                        }],
                    },
                )
                return
            yield TurnEnd(
                stop_reason="end_turn",
                message={"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            )

    times = iter([0.0, 0.0, 46.0, 47.0, 48.0, 49.0, 50.0])
    monkeypatch.setenv("CRYPT_REASONING_STALL_SECONDS", "45")
    monkeypatch.setenv("CRYPT_ARTIFACT_REASONING_STALL_SECONDS", "45")
    monkeypatch.setattr(loop.time, "monotonic", lambda: next(times))
    provider = StallThenToolProvider()
    runtime.configure(provider, str(workspace), session=None)
    runtime.set_show_thinking(False)
    tool = Tool(
        name="stub",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=lambda args: f"ran {args['x']}",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    messages = [{"role": "user", "content": "create a 3d dna html and open it"}]

    loop._run_until_done(provider, messages, 0, 0, render=False)

    assert provider.calls == 3
    assert any(
        block.get("type") == "tool_result" and "ran ok" in block.get("content", "")
        for msg in messages
        for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
        if isinstance(block, dict)
    )


def test_empty_artifact_response_retries_with_tool_instruction(monkeypatch, workspace):
    class EmptyThenToolProvider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def __init__(self) -> None:
            self.calls = 0
            self.seen_messages: list[list[dict]] = []
            self.seen_system: list[str] = []

        def stream_turn(self, messages, tools, system):
            self.calls += 1
            self.seen_messages.append(list(messages))
            self.seen_system.append(system)
            if self.calls == 1:
                yield ThinkingDelta("planning")
                yield TurnEnd(
                    stop_reason="end_turn",
                    message={"role": "assistant", "content": []},
                    usage={"input_tokens": 10, "output_tokens": 3},
                )
                return
            if self.calls == 2:
                assert any(
                    "previous response ended empty" in block.get("text", "")
                    for msg in messages
                    for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
                    if isinstance(block, dict)
                )
                yield TurnEnd(
                    stop_reason="tool_use",
                    message={
                        "role": "assistant",
                        "content": [{
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "stub",
                            "input": {"x": "ok"},
                        }],
                    },
                )
                return
            yield TurnEnd(
                stop_reason="end_turn",
                message={"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            )

    provider = EmptyThenToolProvider()
    runtime.configure(provider, str(workspace), session=None)
    tool = Tool(
        name="stub",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=lambda args: f"ran {args['x']}",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)
    messages = [{"role": "user", "content": "build a single-file animated html and open it"}]

    current_tokens, session_tokens = loop._run_until_done(provider, messages, 0, 0, render=False)

    assert provider.calls == 3
    assert current_tokens == 13
    assert session_tokens == 13
    assert provider.seen_system
    assert "Current Turn Constraint" in provider.seen_system[0]
    assert "must contain a write_file or edit_file tool call" in provider.seen_system[0]
    assert not any(msg.get("role") == "assistant" and msg.get("content") == [] for msg in messages)
    assert any(
        block.get("type") == "tool_result" and "ran ok" in block.get("content", "")
        for msg in messages
        for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
        if isinstance(block, dict)
    )


def test_repeated_empty_artifact_response_errors(monkeypatch, workspace):
    class AlwaysEmptyProvider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def stream_turn(self, messages, tools, system):
            yield TurnEnd(stop_reason="end_turn", message={"role": "assistant", "content": []})

    provider = AlwaysEmptyProvider()
    runtime.configure(provider, str(workspace), session=None)
    messages = [{"role": "user", "content": "build a single-file animated html and open it"}]

    with pytest.raises(RuntimeError, match="empty artifact response after retry"):
        loop._run_until_done(provider, messages, 0, 0, render=False)

    assert not any(msg.get("role") == "assistant" and msg.get("content") == [] for msg in messages)


class _TextThenToolProvider:
    name = "fake"
    model = "fake-model"
    is_oauth = False

    def __init__(self) -> None:
        self.calls = 0
        self.seen_messages: list[list[dict]] = []

    def stream_turn(self, messages, tools, system):
        self.calls += 1
        self.seen_messages.append(list(messages))
        if self.calls == 1:
            yield TextDelta("```html\n")
            raise AssertionError("artifact text stream should be cut immediately")
        if self.calls == 2:
            yield TurnEnd(
                stop_reason="tool_use",
                message={
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "stub",
                            "input": {"x": "ok"},
                        }
                    ],
                },
            )
            return
        yield TextDelta("done")
        yield TurnEnd(
            stop_reason="end_turn",
            message={"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        )


class _TextThenToolNoRenderProvider(_TextThenToolProvider):
    def stream_turn(self, messages, tools, system):
        self.calls += 1
        self.seen_messages.append(list(messages))
        if self.calls == 1:
            text = "```html\n" + ("<section>artifact</section>\n" * 20) + "```"
            yield TextDelta(text)
            yield TurnEnd(
                stop_reason="end_turn",
                message={"role": "assistant", "content": [{"type": "text", "text": text}]},
            )
            return
        if self.calls == 2:
            yield TurnEnd(
                stop_reason="tool_use",
                message={
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "stub",
                            "input": {"x": "ok"},
                        }
                    ],
                },
            )
            return
        yield TextDelta("done")
        yield TurnEnd(
            stop_reason="end_turn",
            message={"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        )


def test_text_only_artifact_answer_is_retried_with_tools(monkeypatch, workspace):
    provider = _TextThenToolNoRenderProvider()
    runtime.configure(provider, str(workspace), session=None)
    tool = Tool(
        name="stub",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=lambda args: f"ran {args['x']}",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    messages = [{"role": "user", "content": "make me a super advanced html"}]
    loop._run_until_done(provider, messages, 0, 0, render=False)

    assert provider.calls == 3
    assert any(
        "pasted the artifact in chat" in block.get("text", "")
        for msg in messages
        for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
        if isinstance(block, dict)
    )
    assert any(
        block.get("type") == "tool_result" and "ran ok" in block.get("content", "")
        for msg in messages
        for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
        if isinstance(block, dict)
    )


def test_rendered_artifact_stream_is_cut_before_full_generation(monkeypatch, workspace):
    provider = _TextThenToolProvider()
    runtime.configure(provider, str(workspace), session=None)
    tool = Tool(
        name="stub",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=lambda args: f"ran {args['x']}",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    messages = [{"role": "user", "content": "make me a super advanced html"}]
    loop._run_until_done(provider, messages, 0, 0, render=True)

    assert provider.calls == 3
    assert any(
        "pasted the artifact in chat" in block.get("text", "")
        for msg in messages
        for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
        if isinstance(block, dict)
    )
    assert any(
        block.get("type") == "tool_result" and "ran ok" in block.get("content", "")
        for msg in messages
        for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
        if isinstance(block, dict)
    )


class _PlanThenToolProvider:
    name = "fake"
    model = "fake-model"
    is_oauth = False

    def __init__(self) -> None:
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
                        "id": "plan_1",
                        "name": "present_plan",
                        "input": {"title": "Demo", "plan": "Create one HTML file."},
                    }],
                },
            )
            return
        if self.calls == 2:
            yield TurnEnd(
                stop_reason="tool_use",
                message={
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "stub",
                        "input": {"x": "ok"},
                    }],
                },
            )
            return
        yield TurnEnd(
            stop_reason="end_turn",
            message={"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        )


def test_present_plan_runs_for_simple_artifact_request(monkeypatch, workspace):
    provider = _PlanThenToolProvider()
    runtime.configure(provider, str(workspace), session=None)
    tool = Tool(
        name="stub",
        description="stub",
        schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        permission="auto",
        run=lambda args: f"ran {args['x']}",
    )
    monkeypatch.setitem(registry.REGISTRY._tools, tool.name, tool)

    messages = [{"role": "user", "content": "make me a super advanced html and open it"}]
    loop._run_until_done(provider, messages, 0, 0, render=False)

    assert provider.calls == 3
    assert any(
        block.get("tool_use_id") == "plan_1"
        and "approved. proceed" in block.get("content", "")
        for msg in messages
        for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
        if isinstance(block, dict)
    )


def test_artifact_request_shows_real_stream_activity(monkeypatch, workspace):
    provider = _FakeProvider()
    runtime.configure(provider, str(workspace), session=None)
    seen: list[str] = []

    monkeypatch.setattr(loop.ui, "activity", lambda label: seen.append(label))
    monkeypatch.setattr(loop.ui, "tool_progress_clear", lambda: None)

    loop._stream_one_turn(
        provider,
        messages=[{"role": "user", "content": "make me an animated html"}],
        tools=[],
        loader=loop._SilentLoader(),
        render=True,
    )

    assert "waiting for file tool call" in seen
    assert "receiving text stream" in seen
    assert "response complete" in seen


def test_real_stream_activity_survives_after_plan_approval(monkeypatch, workspace):
    provider = _FakeProvider()
    runtime.configure(provider, str(workspace), session=None)
    seen: list[str] = []

    monkeypatch.setattr(loop.ui, "activity", lambda label: seen.append(label))
    monkeypatch.setattr(loop.ui, "tool_progress_clear", lambda: None)

    loop._stream_one_turn(
        provider,
        messages=[
            {"role": "user", "content": "make me an animated html and open it"},
            {
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": "plan_1",
                    "name": "present_plan",
                    "input": {"title": "Demo", "plan": "Create one HTML file."},
                }],
            },
            {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "plan_1",
                    "content": "approved. proceed with execution.",
                }],
            },
        ],
        tools=[],
        loader=loop._SilentLoader(),
        render=True,
    )

    assert "waiting for file tool call" in seen
    assert "receiving text stream" in seen
    assert "response complete" in seen
