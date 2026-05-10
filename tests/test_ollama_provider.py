"""OllamaProvider — Anthropic SDK against Ollama's /v1/messages.

Crypt talks to Ollama via the same Anthropic SDK Claude Code uses, with
``base_url`` pointed at Ollama. These tests cover URL normalization, body
shape (auth, thinking config, tool format), and that streamed SDK events
flow through Crypt's shared `_process_event` machinery.

We don't hit the network. The SDK client's ``.messages.create`` is
monkey-patched to feed canned events back into the provider.
"""
from __future__ import annotations

import pytest

from core.api import (
    OllamaProvider,
    TextDelta,
    ThinkingDelta,
    ToolUseProgress,
    TurnEnd,
    _normalize_ollama_host,
)


# ─── URL normalization ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", "http://localhost:11434"),
        ("localhost", "http://localhost:11434"),
        ("localhost:11434", "http://localhost:11434"),
        ("0.0.0.0", "http://localhost:11434"),
        ("http://0.0.0.0", "http://localhost:11434"),
        ("http://0.0.0.0:11434", "http://localhost:11434"),
        ("https://ollama.com", "https://ollama.com"),
        ("https://ollama.com/", "https://ollama.com"),
        ("http://my-server:9000", "http://my-server:9000"),
    ],
)
def test_normalize_ollama_host(raw, expected):
    assert _normalize_ollama_host(raw) == expected


# ─── streaming roundtrip ────────────────────────────────────────────────


class _FakeEvent:
    """Quack like an Anthropic SDK streaming event."""

    def __init__(self, **data):
        self._data = data

    @property
    def type(self):
        return self._data.get("type")

    def model_dump(self):
        return dict(self._data)


class _FakeMessages:
    def __init__(self, events: list[dict]) -> None:
        self._events = events
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return iter(_FakeEvent(**e) for e in self._events)


class _FakeClient:
    def __init__(self, events: list[dict]) -> None:
        self.messages = _FakeMessages(events)


class _AuthFailMessages:
    def create(self, **kwargs):
        raise AuthenticationError("401 Unauthorized")


class _AuthFailClient:
    messages = _AuthFailMessages()


class AuthenticationError(Exception):
    pass


def _make_provider(events, monkeypatch, **kwargs):
    provider = OllamaProvider(model="qwen3-coder:480b-cloud", host="http://localhost:11434", **kwargs)
    fake = _FakeClient(events)
    monkeypatch.setattr(provider, "_client", fake)
    return provider, fake


def test_stream_turn_emits_text_deltas_then_turn_end(monkeypatch):
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "!"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
        {"type": "message_stop"},
    ]
    provider, _ = _make_provider(events, monkeypatch)
    out = list(provider.stream_turn(messages=[{"role": "user", "content": "hi"}], tools=[], system="sys"))

    text_chunks = [ev.text for ev in out if isinstance(ev, TextDelta)]
    assert "".join(text_chunks) == "Hi!"

    turn_end = [ev for ev in out if isinstance(ev, TurnEnd)]
    assert len(turn_end) == 1
    assert turn_end[0].stop_reason == "end_turn"
    msg = turn_end[0].message
    assert msg["role"] == "assistant"
    assert msg["content"] == [{"type": "text", "text": "Hi!"}]


def test_stream_turn_emits_thinking_deltas(monkeypatch):
    """Thinking content blocks flow through as ThinkingDelta events so
    the user sees the model's reasoning in real time."""
    events = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "let me see..."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ]
    provider, _ = _make_provider(events, monkeypatch)
    out = list(provider.stream_turn(messages=[], tools=[], system=""))
    thinking = [ev for ev in out if isinstance(ev, ThinkingDelta)]
    assert len(thinking) == 1
    assert thinking[0].text == "let me see..."


def test_stream_turn_emits_tool_use_progress_and_final_tool_message(monkeypatch):
    """content_block_start (tool_use) → ToolUseProgress; content_block_stop → ToolUseReady.

    This is the eager-dispatch path that makes the per-tool live row
    appear instantly instead of waiting for the entire stream to finish.
    """
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 50, "output_tokens": 0}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "write_file"},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"path":"x.html"'},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": ',"content":"<p/>"}'},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 24}},
        {"type": "message_stop"},
    ]
    provider, _ = _make_provider(events, monkeypatch)
    out = list(provider.stream_turn(messages=[], tools=[], system=""))

    progress = [ev for ev in out if isinstance(ev, ToolUseProgress)]
    assert progress[0].name == "write_file"
    assert progress[0].call_id == "toolu_1"
    assert progress[-1].argument_chars > 0

    turn_end = [ev for ev in out if isinstance(ev, TurnEnd)]
    assert len(turn_end) == 1
    tool_block = [b for b in turn_end[0].message["content"] if b["type"] == "tool_use"][0]
    assert tool_block["name"] == "write_file"
    assert tool_block["input"] == {"path": "x.html", "content": "<p/>"}


def test_stream_turn_sends_anthropic_tool_shape(monkeypatch):
    """Tools should pass straight through as Anthropic-format
    {name, description, input_schema} — no OpenAI function-wrapper."""
    events = [
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 0}},
        {"type": "message_stop"},
    ]
    provider, fake = _make_provider(events, monkeypatch)
    tools = [{
        "name": "echo",
        "description": "say it back",
        "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
    }]
    list(provider.stream_turn(messages=[], tools=tools, system="sys"))

    sent = fake.messages.calls[0]
    assert sent["tools"] == tools
    assert "function" not in sent["tools"][0]


def test_stream_turn_omits_thinking_by_default(monkeypatch):
    """Ollama thinking defaults off so models reach tool calls faster."""
    provider, fake = _make_provider([{"type": "message_stop"}], monkeypatch)
    list(provider.stream_turn(messages=[], tools=[], system=""))
    assert "thinking" not in fake.messages.calls[0]


def test_stream_turn_enables_thinking_when_budget_is_set(monkeypatch):
    monkeypatch.setenv("OLLAMA_THINKING_BUDGET", "2048")
    provider, fake = _make_provider([{"type": "message_stop"}], monkeypatch)
    list(provider.stream_turn(messages=[], tools=[], system=""))
    assert fake.messages.calls[0]["thinking"] == {"type": "enabled", "budget_tokens": 2048}


def test_stream_turn_uses_explicit_thinking_budget(monkeypatch):
    provider, fake = _make_provider([{"type": "message_stop"}], monkeypatch, thinking_budget=4096)
    list(provider.stream_turn(messages=[], tools=[], system=""))
    assert fake.messages.calls[0]["thinking"] == {"type": "enabled", "budget_tokens": 4096}


def test_stream_turn_omits_thinking_when_budget_is_zero(monkeypatch):
    """OLLAMA_THINKING_BUDGET=0 lets users opt out for non-thinking models."""
    monkeypatch.setenv("OLLAMA_THINKING_BUDGET", "0")
    provider, fake = _make_provider([{"type": "message_stop"}], monkeypatch)
    list(provider.stream_turn(messages=[], tools=[], system=""))
    assert "thinking" not in fake.messages.calls[0]


def test_thinking_budget_is_clamped_below_max_tokens(monkeypatch):
    """Anthropic API rejects budget >= max_tokens; provider must clamp."""
    monkeypatch.setenv("OLLAMA_MAX_TOKENS", "4096")
    monkeypatch.setenv("OLLAMA_THINKING_BUDGET", "8000")
    provider = OllamaProvider(model="m", host="http://localhost:11434")
    assert provider._thinking_budget < provider._max_tokens
    assert provider._max_tokens - provider._thinking_budget >= 2048


def test_provider_uses_anthropic_sdk_client():
    """Smoke check: the SDK client is constructed with the right base_url."""
    provider = OllamaProvider(model="m", host="https://ollama.com")
    # The SDK's Anthropic client exposes the base URL on its underlying
    # http client. We just verify the provider was wired with our URL.
    assert str(provider._client.base_url).rstrip("/") == "https://ollama.com"


def test_cloud_auth_error_explains_ollama_key(monkeypatch):
    provider = OllamaProvider(model="m", host="https://ollama.com")
    monkeypatch.setattr(provider, "_client", _AuthFailClient())

    with pytest.raises(RuntimeError) as exc:
        list(provider.stream_turn(messages=[], tools=[], system=""))

    message = str(exc.value)
    assert "Ollama authentication failed" in message
    assert "OLLAMA_API_KEY" in message
    assert "Anthropic OAuth" in message
