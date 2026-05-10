from __future__ import annotations

import json

import pytest

from core.api import GeminiProvider, TextDelta, ToolUseProgress, TurnEnd


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
        return self.text.encode()

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


def test_gemini_api_key_stream_uses_developer_api(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider(
        model="gemini-2.5-flash",
        api_key="test-key",
        max_tokens=256,
    )
    provider._http = _FakeHTTP([
        _sse({
            "candidates": [{"content": {"parts": [{"text": "hi"}]}}],
            "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1, "totalTokenCount": 3},
        }),
    ])

    out = list(provider.stream_turn(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        system="sys",
    ))

    assert any(isinstance(event, TextDelta) and event.text == "hi" for event in out)
    end = [event for event in out if isinstance(event, TurnEnd)][0]
    assert end.message["content"] == [{"type": "text", "text": "hi"}]
    assert end.usage == {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
    call = provider._http.calls[0]
    assert call["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-2.5-flash:streamGenerateContent?alt=sse"
    )
    assert call["headers"]["x-goog-api-key"] == "test-key"
    assert "Authorization" not in call["headers"]
    assert call["json"]["systemInstruction"] == {"parts": [{"text": "sys"}]}
    assert call["json"]["generationConfig"]["maxOutputTokens"] == 256


def test_gemini_oauth_stream_uses_vertex_ai_and_tool_calls(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider(
        model="models/gemini-2.5-pro",
        auth_token="oauth-token",
        project_id="project-123",
        location="us-central1",
    )
    provider._http = _FakeHTTP([
        _sse({
            "candidates": [{
                "content": {
                    "parts": [{
                        "functionCall": {
                            "name": "read_file",
                            "args": {"path": "README.md"},
                        },
                    }],
                },
            }],
        }),
    ])
    tools = [{
        "name": "read_file",
        "description": "read a file",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
    }]

    out = list(provider.stream_turn(
        messages=[{"role": "user", "content": "inspect"}],
        tools=tools,
        system="sys",
    ))

    progress = [event for event in out if isinstance(event, ToolUseProgress)][0]
    assert progress.name == "read_file"
    end = [event for event in out if isinstance(event, TurnEnd)][0]
    assert end.stop_reason == "tool_use"
    assert end.message["content"] == [{
        "type": "tool_use",
        "id": "gemini_call_0",
        "name": "read_file",
        "input": {"path": "README.md"},
    }]
    call = provider._http.calls[0]
    assert call["url"] == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/project-123/locations/us-central1/"
        "publishers/google/models/gemini-2.5-pro:streamGenerateContent?alt=sse"
    )
    assert call["headers"]["Authorization"] == "Bearer oauth-token"
    assert call["headers"]["x-goog-user-project"] == "project-123"


def test_gemini_oauth_scope_error_explains_relogin_and_vertex(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider(
        auth_token="oauth-token",
        project_id="project-123",
    )
    provider._http = _FakeHTTP(
        [],
        status_code=403,
        text=json.dumps({
            "error": {
                "message": "Request had insufficient authentication scopes.",
                "details": [{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}],
            },
        }),
    )

    with pytest.raises(RuntimeError) as exc:
        list(provider.stream_turn(messages=[{"role": "user", "content": "hi"}], tools=[], system=""))

    message = str(exc.value)
    assert "Gemini OAuth is routed through Vertex AI" in message
    assert "python -m crypt login --provider gemini" in message
    assert "GEMINI_PROJECT_ID" in message
    assert "GEMINI_API_KEY" in message


def test_gemini_oauth_without_project_id_uses_developer_api(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider(
        model="gemini-2.5-flash",
        auth_token="oauth-token",
        project_id="",
    )
    provider._http = _FakeHTTP([
        _sse({
            "candidates": [{"content": {"parts": [{"text": "hi"}]}}],
        }),
    ])

    list(provider.stream_turn(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        system="sys",
    ))

    call = provider._http.calls[0]
    assert call["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-2.5-flash:streamGenerateContent?alt=sse"
    )
    assert call["headers"]["Authorization"] == "Bearer oauth-token"
    assert "x-goog-user-project" not in call["headers"]
