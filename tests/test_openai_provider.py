from __future__ import annotations

import json

import pytest

from core.api import (
    AnthropicProvider,
    OpenAICodexProvider,
    OpenAIProvider,
    TextDelta,
    ThinkingDelta,
    ToolUseProgress,
    ToolUseReady,
    TurnEnd,
)


class _FakeStreamResponse:
    def __init__(self, chunks: list[str], status_code: int = 200, text: str = "") -> None:
        self._chunks = chunks
        self.status_code = status_code
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return b""

    def iter_text(self):
        yield from self._chunks


class _FakeHTTP:
    def __init__(self, chunks: list[str], status_code: int = 200, text: str = "") -> None:
        self._chunks = chunks
        self._status_code = status_code
        self._text = text
        self.calls: list[dict] = []

    def stream(self, method, url, *, json, headers):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return _FakeStreamResponse(self._chunks, self._status_code, self._text)


def _sse(data: dict) -> str:
    return "data: " + json.dumps(data) + "\n\n"


def _anthropic_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def test_anthropic_oauth_stream_uses_claude_code_request_shape():
    chunks = [
        _anthropic_sse(
            "message_start",
            {"message": {"usage": {"input_tokens": 12, "output_tokens": 0}}},
        ),
        _anthropic_sse(
            "content_block_start",
            {"index": 0, "content_block": {"type": "text"}},
        ),
        _anthropic_sse(
            "content_block_delta",
            {"index": 0, "delta": {"type": "text_delta", "text": "checking"}},
        ),
        _anthropic_sse(
            "content_block_start",
            {
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "read_file",
                },
            },
        ),
        _anthropic_sse(
            "content_block_delta",
            {"index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"path":"README.md"'}},
        ),
        _anthropic_sse(
            "content_block_delta",
            {"index": 1, "delta": {"type": "input_json_delta", "partial_json": "}"}},
        ),
        _anthropic_sse("content_block_stop", {"index": 1}),
        _anthropic_sse(
            "message_delta",
            {"delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 9}},
        ),
        _anthropic_sse("message_stop", {}),
    ]
    provider = AnthropicProvider(
        model="claude-test",
        max_tokens=4096,
        thinking_budget=1024,
        auth_token="oauth-token",
    )
    provider._http = _FakeHTTP(chunks)
    tools = [{
        "name": "read_file",
        "description": "read a file",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
    }]

    out = list(provider.stream_turn(
        messages=[{"role": "user", "content": "inspect"}],
        tools=tools,
        system="system prompt",
    ))

    assert any(isinstance(event, TextDelta) and event.text == "checking" for event in out)
    ready = [event for event in out if isinstance(event, ToolUseReady)]
    assert ready and ready[0].tool == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "read_file",
        "input": {"path": "README.md"},
    }
    progress = [event for event in out if isinstance(event, ToolUseProgress)]
    assert progress[-1].partial_json == '{"path":"README.md"}'
    turn_end = [event for event in out if isinstance(event, TurnEnd)][0]
    assert turn_end.stop_reason == "tool_use"
    assert turn_end.usage == {"input_tokens": 12, "output_tokens": 9}

    call = provider._http.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["Authorization"] == "Bearer oauth-token"
    assert call["headers"]["x-app"]
    assert call["headers"]["user-agent"]
    assert call["json"]["system"][0]["text"].startswith("You are Claude Code")
    assert call["json"]["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert call["json"]["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert call["json"]["thinking"] == {"type": "enabled", "budget_tokens": 1024}


def test_anthropic_escalate_once_only_affects_next_request():
    provider = AnthropicProvider(
        model="claude-test",
        max_tokens=2048,
        thinking_budget=0,
        auth_token="oauth-token",
    )
    chunks = [
        _anthropic_sse("message_delta", {"delta": {"stop_reason": "end_turn"}}),
        _anthropic_sse("message_stop", {}),
    ]
    provider._http = _FakeHTTP(chunks)

    provider.escalate_once(9000)
    list(provider.stream_turn(messages=[], tools=[], system="sys"))
    list(provider.stream_turn(messages=[], tools=[], system="sys"))

    assert provider._http.calls[0]["json"]["max_tokens"] == 9000
    assert provider._http.calls[1]["json"]["max_tokens"] == 2048


def test_openai_tool_progress_includes_partial_json():
    first_args = '{"path":"demo.html"'
    second_args = ',"content":"<p>hi</p>"}'
    chunks = [
        _sse({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_1",
                        "function": {
                            "name": "write_file",
                            "arguments": first_args,
                        },
                    }],
                },
                "finish_reason": None,
            }],
        }),
        _sse({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": second_args},
                    }],
                },
                "finish_reason": None,
            }],
        }),
        _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        "data: [DONE]\n\n",
    ]
    provider = OpenAIProvider(
        model="gpt-test",
        api_key="test-key",
        base_url="http://openai.test/v1",
    )
    provider._http = _FakeHTTP(chunks)

    out = list(provider.stream_turn(messages=[], tools=[], system="sys"))

    progress = [event for event in out if isinstance(event, ToolUseProgress)]
    assert progress[-1].name == "write_file"
    assert progress[-1].call_id == "call_1"
    assert progress[-1].partial_json == first_args + second_args
    assert progress[-1].argument_chars == len(first_args + second_args)

    turn_end = [event for event in out if isinstance(event, TurnEnd)][0]
    assert turn_end.stop_reason == "tool_use"
    assert turn_end.message["content"][0]["input"] == {
        "path": "demo.html",
        "content": "<p>hi</p>",
    }


def test_openai_stream_preserves_text_before_tool_and_maps_length_stop():
    chunks = [
        _sse({
            "choices": [{
                "delta": {"content": "I will inspect first. "},
                "finish_reason": None,
            }],
        }),
        _sse({
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                    }],
                },
                "finish_reason": None,
            }],
        }),
        _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        "data: [DONE]\n\n",
    ]
    provider = OpenAIProvider(
        model="gpt-test",
        api_key="test-key",
        base_url="http://openai.test/v1",
    )
    provider._http = _FakeHTTP(chunks)

    turn_end = [event for event in provider.stream_turn(messages=[], tools=[], system="sys")
                if isinstance(event, TurnEnd)][0]

    assert turn_end.stop_reason == "tool_use"
    assert turn_end.message["content"] == [
        {"type": "text", "text": "I will inspect first. "},
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "read_file",
            "input": {"path": "README.md"},
        },
    ]

    provider._http = _FakeHTTP([
        _sse({"choices": [{"delta": {"content": "partial"}, "finish_reason": "length"}]}),
        "data: [DONE]\n\n",
    ])

    turn_end = [event for event in provider.stream_turn(messages=[], tools=[], system="sys")
                if isinstance(event, TurnEnd)][0]

    assert turn_end.stop_reason == "max_tokens"


def test_openai_http_error_includes_status_and_body():
    provider = OpenAIProvider(
        model="gpt-test",
        api_key="test-key",
        base_url="http://openai.test/v1",
    )
    provider._http = _FakeHTTP([], status_code=429, text="slow down")

    with pytest.raises(RuntimeError) as exc:
        list(provider.stream_turn(messages=[], tools=[], system="sys"))

    message = str(exc.value)
    assert "openai HTTP 429" in message
    assert "slow down" in message


def test_openai_reasoning_model_uses_reasoning_effort():
    provider = OpenAIProvider(
        model="o3-mini",
        api_key="test-key",
        reasoning_effort="high",
    )

    body = provider._build_body(messages=[], tools=[], system="sys")

    assert body["max_completion_tokens"]
    assert body["reasoning_effort"] == "high"


def test_openai_codex_uses_chatgpt_backend_headers_and_responses_body():
    chunks = [
        _sse({"type": "response.output_text.delta", "delta": "hi"}),
        _sse({"type": "response.completed", "response": {"status": "completed"}}),
    ]
    provider = OpenAICodexProvider(
        model="gpt-5-codex",
        auth_token="chatgpt-token",
        account_id="account-123",
        base_url="https://chatgpt.com/backend-api",
    )
    provider._http = _FakeHTTP(chunks)

    out = list(provider.stream_turn(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        system="sys",
    ))

    assert any(isinstance(event, TextDelta) and event.text == "hi" for event in out)
    call = provider._http.calls[0]
    assert call["url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert call["headers"]["Authorization"] == "Bearer chatgpt-token"
    assert call["headers"]["ChatGPT-Account-ID"] == "account-123"
    assert call["headers"]["OpenAI-Beta"] == "responses=experimental"
    assert call["json"]["instructions"] == "sys"
    assert "max_output_tokens" not in call["json"]
    assert "max_tokens" not in call["json"]
    assert "max_completion_tokens" not in call["json"]
    assert call["json"]["input"] == [{
        "role": "user",
        "content": [{"type": "input_text", "text": "hello"}],
    }]


def test_openai_codex_stream_maps_reasoning_and_tool_calls():
    chunks = [
        _sse({"type": "response.reasoning_summary_text.delta", "delta": "plan"}),
        _sse({
            "type": "response.output_item.added",
            "item": {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_1",
                "name": "write_file",
                "arguments": "",
            },
        }),
        _sse({
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_1",
            "delta": '{"path":"demo.html"',
        }),
        _sse({
            "type": "response.function_call_arguments.done",
            "item_id": "fc_1",
            "arguments": '{"path":"demo.html","content":"<p>hi</p>"}',
        }),
        _sse({"type": "response.completed", "response": {"status": "completed"}}),
    ]
    provider = OpenAICodexProvider(
        model="gpt-5-codex",
        auth_token="chatgpt-token",
        account_id="account-123",
        base_url="https://chatgpt.com/backend-api",
    )
    provider._http = _FakeHTTP(chunks)

    out = list(provider.stream_turn(messages=[], tools=[], system="sys"))

    assert any(isinstance(event, ThinkingDelta) and event.text == "plan" for event in out)
    progress = [event for event in out if isinstance(event, ToolUseProgress)]
    assert progress[-1].name == "write_file"
    assert progress[-1].call_id == "call_1"
    turn_end = [event for event in out if isinstance(event, TurnEnd)][0]
    assert turn_end.stop_reason == "tool_use"
    assert turn_end.message["content"][0]["name"] == "write_file"
    assert turn_end.message["content"][0]["input"] == {
        "path": "demo.html",
        "content": "<p>hi</p>",
    }


def test_openai_codex_body_uses_reasoning_effort():
    provider = OpenAICodexProvider(
        model="gpt-5-codex",
        auth_token="chatgpt-token",
        account_id="account-123",
        reasoning_effort="high",
    )

    body = provider._build_body(messages=[], tools=[], system="sys")

    assert body["reasoning"] == {"effort": "high", "summary": "auto"}


def test_openai_codex_maps_incomplete_and_failed_events():
    provider = OpenAICodexProvider(
        model="gpt-5-codex",
        auth_token="chatgpt-token",
        account_id="account-123",
        base_url="https://chatgpt.com/backend-api",
    )
    provider._http = _FakeHTTP([
        _sse({
            "type": "response.incomplete",
            "response": {
                "status": "incomplete",
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        }),
    ])

    turn_end = [event for event in provider.stream_turn(messages=[], tools=[], system="sys")
                if isinstance(event, TurnEnd)][0]

    assert turn_end.stop_reason == "max_tokens"
    assert turn_end.usage == {"input_tokens": 1, "output_tokens": 2}

    provider._http = _FakeHTTP([
        _sse({
            "type": "response.failed",
            "response": {"error": {"message": "backend refused"}},
        }),
    ])

    with pytest.raises(RuntimeError) as exc:
        list(provider.stream_turn(messages=[], tools=[], system="sys"))

    assert "backend refused" in str(exc.value)
