"""Provider adapters.

Internal messages use Anthropic-style content blocks:
    {"role": "user" | "assistant", "content": str | [block, ...]}

The Anthropic path uses raw httpx, not the anthropic-python SDK, because
the SDK injects X-Stainless-* fingerprint headers that the Anthropic edge
uses to detect non-Claude-Code OAuth traffic and silently rate-limit it.
Mirrors MrDoing's `mrdoing/stream.py`.
"""
from __future__ import annotations

import atexit
import json
import os
import threading
from dataclasses import dataclass
from typing import Iterator, Protocol

import httpx

from .settings import (
    ANTHROPIC_BASE_BETAS,
    ANTHROPIC_ESCALATED_MAX_TOKENS,
    ANTHROPIC_MAX_TOKENS,
    ANTHROPIC_MODEL,
    ANTHROPIC_OAUTH_BETAS,
    ANTHROPIC_OAUTH_USER_AGENT,
    ANTHROPIC_OAUTH_X_APP,
    ANTHROPIC_THINKING_BUDGET,
    GEMINI_BASE_URL,
    GEMINI_MAX_TOKENS,
    GEMINI_MODEL,
    GEMINI_VERTEX_LOCATION,
    OLLAMA_MODEL,
    OPENAI_BASE_URL,
    OPENAI_CODEX_BASE_URL,
    OPENAI_CODEX_MAX_TOKENS,
    OPENAI_CODEX_MODEL,
    OPENAI_MAX_TOKENS,
    OPENAI_MODEL,
)


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class ToolUseProgress:
    name: str
    call_id: str = ""
    argument_chars: int = 0
    partial_json: str = ""


@dataclass
class ToolUseReady:
    message: dict
    usage: dict | None = None
    tool: dict | None = None


@dataclass
class TurnEnd:
    stop_reason: str
    message: dict
    usage: dict | None = None
    text_buffered: bool = False
    tool_results: list[dict] | None = None


Event = TextDelta | ThinkingDelta | ToolUseProgress | ToolUseReady | TurnEnd


class Provider(Protocol):
    name: str
    model: str
    is_oauth: bool

    def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> Iterator[Event]: ...


_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
# Prepended to system blocks on OAuth so the server's OAuth path
# recognizes us as Claude Code. MUST be the first system block.
_CLAUDE_CODE_IDENTITY = (
    "You are Claude Code, Anthropic's official CLI for Claude."
)


class AnthropicProvider:
    name = "anthropic"
    context_window = 1_000_000

    def __init__(
        self,
        model: str = ANTHROPIC_MODEL,
        max_tokens: int = ANTHROPIC_MAX_TOKENS,
        thinking_budget: int = ANTHROPIC_THINKING_BUDGET,
        auth_token: str | None = None,
    ) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not auth_token and not api_key:
            raise RuntimeError(
                "AnthropicProvider needs either an OAuth auth_token or "
                "ANTHROPIC_API_KEY in the environment."
            )
        self._auth_token = auth_token
        self._api_key = api_key
        self._oauth = bool(auth_token)
        self._lock = threading.RLock()
        self.model = model
        self._max_tokens = max_tokens
        self._max_tokens_override = 0
        # Thinking budget must stay strictly below max_tokens; the API
        # rejects budgets >= max_tokens. Anthropic also requires a 1024
        # minimum when thinking is enabled — clamp up to honor intent.
        if thinking_budget <= 0 or max_tokens < 1025:
            self._thinking_budget = 0
        else:
            self._thinking_budget = max(1024, min(thinking_budget, max_tokens - 1))
        self._http = httpx.Client(timeout=httpx.Timeout(10.0, read=180.0))
        # Don't leak the connection pool when Python exits. atexit is
        # a process-wide hook; multiple providers register multiple
        # close handlers and that's fine — close() is idempotent.
        atexit.register(self.close)

    @property
    def is_oauth(self) -> bool:
        return self._oauth

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass

    def escalate_once(self, escalated: int = ANTHROPIC_ESCALATED_MAX_TOKENS) -> int:
        """Arm a one-shot max_tokens override for the next stream_turn().

        Used by the loop when a turn ends with stop_reason='max_tokens' so we
        get one clean retry at a higher budget. The override clears itself
        after the next API call.
        """
        with self._lock:
            self._max_tokens_override = max(escalated, self._max_tokens)
            return self._max_tokens_override

    def _build_request(self, messages, tools, system):
        with self._lock:
            max_tokens = self._max_tokens_override or self._max_tokens
            self._max_tokens_override = 0
        if self._thinking_budget and self._thinking_budget >= max_tokens:
            thinking_budget = max(0, max_tokens - 1)
            if thinking_budget < 1024:
                thinking_budget = 0
        else:
            thinking_budget = self._thinking_budget

        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "anthropic-version": "2023-06-01",
            "anthropic-dangerous-direct-browser-access": "true",
        }
        if self._oauth:
            headers["Authorization"] = f"Bearer {self._auth_token}"
            headers["anthropic-beta"] = ANTHROPIC_OAUTH_BETAS
            headers["user-agent"] = ANTHROPIC_OAUTH_USER_AGENT
            headers["x-app"] = ANTHROPIC_OAUTH_X_APP
            system_blocks = [
                {"type": "text", "text": _CLAUDE_CODE_IDENTITY},
                {"type": "text", "text": system},
            ]
        else:
            headers["x-api-key"] = self._api_key
            headers["anthropic-beta"] = ANTHROPIC_BASE_BETAS
            system_blocks = [{"type": "text", "text": system}]

        # Cache breakpoints: Anthropic allows 4 cache_control markers per
        # request and caches everything up to and including the marked
        # block. Spend them on system + tools + last 2 user messages so
        # multi-turn sessions get deep cache hits.
        system_blocks = _mark_last_for_cache(system_blocks)
        cached_tools = _mark_last_for_cache(list(tools)) if tools else []
        cached_messages = _mark_messages_for_cache(messages)

        body: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system_blocks,
            "messages": cached_messages,
            "stream": True,
        }
        if cached_tools:
            body["tools"] = cached_tools
        if thinking_budget:
            body["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        return headers, body

    def stream_turn(self, messages, tools, system):
        headers, body = self._build_request(messages, tools, system)
        url = f"{_ANTHROPIC_BASE_URL}/v1/messages"

        with self._http.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                _raise_for_status(resp)

            content_blocks: list[dict | None] = []
            usage: dict = {"input_tokens": 0, "output_tokens": 0}
            stop_reason = "end_turn"
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    parsed = _parse_sse(block)
                    if parsed is None:
                        continue
                    event_type, data = parsed
                    for ev in _process_event(event_type, data, content_blocks, usage):
                        if isinstance(ev, _StopReason):
                            stop_reason = ev.value
                        else:
                            yield ev

        yield TurnEnd(
            stop_reason=stop_reason,
            message=_finalized_assistant_message(content_blocks),
            usage=usage,
        )


@dataclass
class _StopReason:
    value: str


def _parse_sse(block: str):
    event_type = None
    data_parts: list[str] = []
    for line in block.splitlines():
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_parts.append(line[5:].lstrip())
    if not event_type or not data_parts:
        return None
    try:
        return event_type, json.loads("\n".join(data_parts))
    except json.JSONDecodeError:
        return None


def _process_event(event_type, data, content_blocks, usage):
    if event_type == "message_start":
        u = (data.get("message") or {}).get("usage") or {}
        usage["input_tokens"] = u.get("input_tokens", 0)
        usage["output_tokens"] = u.get("output_tokens", 0)
        return

    if event_type == "content_block_start":
        try:
            index = int(data.get("index", 0))
        except (TypeError, ValueError):
            return
        meta = data.get("content_block") or {}
        btype = meta.get("type")
        while len(content_blocks) <= index:
            content_blocks.append(None)
        if btype == "text":
            content_blocks[index] = {"type": "text", "text": ""}
        elif btype == "thinking":
            content_blocks[index] = {"type": "thinking", "thinking": ""}
        elif btype == "tool_use":
            content_blocks[index] = {
                "type": "tool_use",
                "id": meta.get("id") or f"tool_{index}",
                "name": meta.get("name") or "?",
                "input": {},
                "_partial_json": "",
            }
            yield ToolUseProgress(
                name=content_blocks[index]["name"],
                call_id=content_blocks[index]["id"],
                argument_chars=0,
                partial_json="",
            )
        return

    if event_type == "content_block_delta":
        try:
            index = int(data.get("index", 0))
        except (TypeError, ValueError):
            return
        if index < 0 or index >= len(content_blocks) or content_blocks[index] is None:
            return
        block = content_blocks[index]
        delta = data.get("delta") or {}
        dtype = delta.get("type")
        if dtype == "text_delta":
            text = delta.get("text", "")
            block["text"] = block.get("text", "") + text
            yield TextDelta(text)
        elif dtype == "thinking_delta":
            text = delta.get("thinking", "")
            block["thinking"] = block.get("thinking", "") + text
            yield ThinkingDelta(text)
        elif dtype == "input_json_delta":
            partial = delta.get("partial_json", "")
            block["_partial_json"] = block.get("_partial_json", "") + partial
            yield ToolUseProgress(
                name=str(block.get("name") or "?"),
                call_id=str(block.get("id") or ""),
                argument_chars=len(str(block.get("_partial_json") or "")),
                partial_json=str(block.get("_partial_json") or ""),
            )
        return

    if event_type == "content_block_stop":
        try:
            index = int(data.get("index", 0))
        except (TypeError, ValueError):
            return
        if index < 0 or index >= len(content_blocks):
            return
        block = content_blocks[index]
        if isinstance(block, dict) and block.get("type") == "tool_use":
            raw = block.get("_partial_json", "")
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {}
            block["input"] = parsed if isinstance(parsed, dict) else {}
            clean = {
                key: value
                for key, value in block.items()
                if not key.startswith("_")
            }
            yield ToolUseReady(
                message=_finalized_assistant_message(content_blocks),
                usage=usage,
                tool=clean,
            )
        return

    if event_type == "message_delta":
        u = data.get("usage") or {}
        if "output_tokens" in u:
            usage["output_tokens"] = u["output_tokens"]
        sr = (data.get("delta") or {}).get("stop_reason")
        if sr:
            yield _StopReason(sr)
        return

    if event_type == "error":
        err = data.get("error") or {}
        raise RuntimeError(f"stream error: {err.get('message') or err}")


def _finalized_assistant_message(content_blocks: list[dict | None]) -> dict:
    # Drop thinking blocks from persisted history. Anthropic requires a
    # signature on round-tripped thinking blocks; the UI may show them, but
    # the transcript should not resend them.
    content: list[dict] = []
    for block in content_blocks:
        if not block or block.get("type") == "thinking":
            continue
        clean = {
            key: value
            for key, value in block.items()
            if not key.startswith("_")
        }
        if clean.get("type") == "tool_use":
            raw = block.get("_partial_json", "")
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {}
            clean["input"] = parsed if isinstance(parsed, dict) else {}
        content.append(clean)
    return {"role": "assistant", "content": content}


def _mark_cache_breakpoint(block: dict) -> dict:
    return {**block, "cache_control": {"type": "ephemeral"}}


def _mark_last_for_cache(items: list[dict]) -> list[dict]:
    if not items:
        return items
    return items[:-1] + [_mark_cache_breakpoint(items[-1])]


def _mark_messages_for_cache(messages: list[dict]) -> list[dict]:
    if not messages:
        return messages
    out = list(messages)
    marked = 0
    for idx in range(len(out) - 1, -1, -1):
        msg = out[idx]
        if msg.get("role") != "user":
            continue
        out[idx] = _cache_mark_user_message(msg)
        marked += 1
        if marked >= 2:
            break
    return out


def _cache_mark_user_message(msg: dict) -> dict:
    content = msg.get("content")
    if isinstance(content, str):
        return {
            **msg,
            "content": [{
                "type": "text",
                "text": content,
                "cache_control": {"type": "ephemeral"},
            }],
        }
    if isinstance(content, list) and content:
        new_content = list(content)
        last = new_content[-1]
        if isinstance(last, dict):
            new_content[-1] = {**last, "cache_control": {"type": "ephemeral"}}
        return {**msg, "content": new_content}
    return msg


def _raise_for_status(resp: httpx.Response) -> None:
    """Map an HTTP error response onto an anthropic SDK exception so
    loop._format_error keeps recognizing it (RateLimitError etc.)."""
    try:
        resp.read()
        body = resp.json() if resp.text else {}
    except Exception:
        body = {}
    msg = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
    msg = msg or resp.text or f"HTTP {resp.status_code}"
    from anthropic import (
        APIStatusError,
        AuthenticationError,
        BadRequestError,
        InternalServerError,
        NotFoundError,
        PermissionDeniedError,
        RateLimitError,
        UnprocessableEntityError,
    )
    cls = {
        400: BadRequestError,
        401: AuthenticationError,
        403: PermissionDeniedError,
        404: NotFoundError,
        422: UnprocessableEntityError,
        429: RateLimitError,
        500: InternalServerError,
    }.get(resp.status_code, APIStatusError)
    raise cls(message=msg, response=resp, body=body)


class OpenAIProvider:
    """OpenAI Chat Completions adapter with streaming + tool calls.

    Works against the official endpoint and any OpenAI-compatible server
    (Together, Fireworks, LM Studio, vLLM, etc.) via OPENAI_BASE_URL. The
    internal message shape stays Anthropic-style; we convert in/out at
    the wire boundary.

    o-series models (o1/o3) get reasoning_effort=medium by default — no
    setting because the API rejects unknown reasoning params on classic
    models. We sniff the model name to pick the right parameter set.
    """
    name = "openai"
    context_window = 128_000
    is_oauth = False

    def __init__(
        self,
        model: str = OPENAI_MODEL,
        max_tokens: int = OPENAI_MAX_TOKENS,
        api_key: str | None = None,
        base_url: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OpenAIProvider needs an API key (set OPENAI_API_KEY or pass api_key)."
            )
        self._api_key = key
        self.model = model
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._base_url = (base_url or os.getenv("OPENAI_BASE_URL") or OPENAI_BASE_URL).rstrip("/")
        self._http = httpx.Client(timeout=httpx.Timeout(10.0, read=180.0))
        atexit.register(self.close)

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass

    def stream_turn(self, messages, tools, system):
        body = self._build_body(messages, tools, system)
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self._api_key}",
        }

        text_buf: list[str] = []
        # Tool calls arrive as deltas keyed by index. Each call has a
        # stable id (eventually), name, and JSON arguments built up over
        # multiple chunks. We assemble per-index, then emit once at the end.
        tool_calls: dict[int, dict] = {}
        finish_reason = "stop"

        with self._http.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                resp.read()
                raise RuntimeError(
                    f"openai HTTP {resp.status_code}: {resp.text[:500]}"
                )
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.rstrip("\r")
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    fr = choice.get("finish_reason")
                    if fr:
                        finish_reason = fr

                    text = delta.get("content")
                    if text:
                        text_buf.append(text)
                        yield TextDelta(text)

                    for call_delta in delta.get("tool_calls") or []:
                        idx = call_delta.get("index", 0)
                        slot = tool_calls.setdefault(idx, {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        })
                        if call_delta.get("id"):
                            slot["id"] = call_delta["id"]
                        fn = call_delta.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                        if slot.get("name"):
                            yield ToolUseProgress(
                                name=slot["name"],
                                call_id=slot.get("id", ""),
                                argument_chars=len(slot.get("arguments") or ""),
                                partial_json=slot.get("arguments") or "",
                            )
        content: list[dict] = []
        if text_buf:
            content.append({"type": "text", "text": "".join(text_buf)})
        for idx in sorted(tool_calls):
            slot = tool_calls[idx]
            block = _openai_tool_block(idx, slot, allow_incomplete=True)
            if block is not None:
                content.append(block)

        # Map OpenAI finish_reason onto our internal stop_reason vocabulary
        # so the loop's max_tokens-escalate path keeps working uniformly.
        if finish_reason == "tool_calls":
            stop = "tool_use"
        elif finish_reason == "length":
            stop = "max_tokens"
        else:
            stop = "end_turn"

        yield TurnEnd(
            stop_reason=stop,
            message={"role": "assistant", "content": content},
        )

    def _build_body(self, messages, tools, system):
        msgs = [{"role": "system", "content": system}]
        msgs.extend(_to_openai_messages(messages))
        body: dict = {
            "model": self.model,
            "messages": msgs,
            "stream": True,
        }
        # o-series uses max_completion_tokens; classic uses max_tokens.
        # Sending the wrong one is a 400 on either side.
        if self._is_reasoning_model():
            body["max_completion_tokens"] = self._max_tokens
            if self._reasoning_effort:
                body["reasoning_effort"] = self._reasoning_effort
        else:
            body["max_tokens"] = self._max_tokens
        if tools:
            body["tools"] = [_to_openai_tool(t) for t in tools]
            body["tool_choice"] = "auto"
        return body

    def _is_reasoning_model(self) -> bool:
        m = self.model.lower()
        return m.startswith("o1") or m.startswith("o3") or m.startswith("o4")


class OpenAICodexProvider:
    """ChatGPT OAuth adapter for OpenAI Codex's Responses backend.

    This is intentionally separate from ``OpenAIProvider``. ChatGPT/Codex
    subscription auth does not speak the classic Chat Completions endpoint;
    it uses the Codex Responses backend with a ChatGPT OAuth bearer token and
    a ``ChatGPT-Account-ID`` routing header.
    """

    name = "openai-codex"
    context_window = 272_000
    is_oauth = True

    def __init__(
        self,
        model: str = OPENAI_CODEX_MODEL,
        auth_token: str | None = None,
        account_id: str | None = None,
        max_tokens: int = OPENAI_CODEX_MAX_TOKENS,
        base_url: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        if not auth_token:
            raise RuntimeError("OpenAICodexProvider needs ChatGPT OAuth auth_token.")
        if not account_id:
            raise RuntimeError("OpenAICodexProvider needs ChatGPT account_id.")
        self._auth_token = auth_token
        self._account_id = account_id
        self.model = model
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._base_url = (base_url or os.getenv("OPENAI_CODEX_BASE_URL") or OPENAI_CODEX_BASE_URL).rstrip("/")
        self._http = httpx.Client(timeout=httpx.Timeout(10.0, read=300.0))
        atexit.register(self.close)

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass

    def stream_turn(self, messages, tools, system):
        body = self._build_body(messages, tools, system)
        url = _codex_responses_url(self._base_url)
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self._auth_token}",
            "ChatGPT-Account-ID": self._account_id,
            "OpenAI-Beta": "responses=experimental",
            "originator": "crypt",
            "User-Agent": "crypt",
        }

        text_buf: list[str] = []
        tool_calls: dict[str, dict] = {}
        stop = "end_turn"
        usage: dict | None = None

        with self._http.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                resp.read()
                raise RuntimeError(
                    f"openai-codex HTTP {resp.status_code}: {resp.text[:500]}"
                )
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.rstrip("\r")
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    event_type = str(event.get("type") or "")
                    if event_type == "error":
                        err = event.get("error") or event
                        raise RuntimeError(f"openai-codex error: {err}")

                    if event_type == "response.output_text.delta":
                        text = str(event.get("delta") or "")
                        if text:
                            text_buf.append(text)
                            yield TextDelta(text)
                        continue

                    if "reasoning" in event_type and event_type.endswith(".delta"):
                        text = str(event.get("delta") or "")
                        if text:
                            yield ThinkingDelta(text)
                        continue

                    if event_type == "response.output_item.added":
                        item = event.get("item") or {}
                        if isinstance(item, dict) and item.get("type") == "function_call":
                            key = _responses_tool_key(event, item)
                            slot = tool_calls.setdefault(key, {
                                "id": item.get("call_id") or item.get("id") or key,
                                "name": item.get("name") or "",
                                "arguments": item.get("arguments") or "",
                            })
                            if item.get("name"):
                                slot["name"] = item["name"]
                        continue

                    if event_type == "response.function_call_arguments.delta":
                        key = _responses_tool_key(event, event)
                        slot = tool_calls.setdefault(key, {
                            "id": event.get("call_id") or key,
                            "name": event.get("name") or "",
                            "arguments": "",
                        })
                        delta = str(event.get("delta") or "")
                        slot["arguments"] += delta
                        if event.get("name"):
                            slot["name"] = event["name"]
                        if slot.get("name"):
                            yield ToolUseProgress(
                                name=slot["name"],
                                call_id=slot.get("id", ""),
                                argument_chars=len(slot.get("arguments") or ""),
                                partial_json=slot.get("arguments") or "",
                            )
                        continue

                    if event_type == "response.function_call_arguments.done":
                        key = _responses_tool_key(event, event)
                        slot = tool_calls.setdefault(key, {
                            "id": event.get("call_id") or key,
                            "name": event.get("name") or "",
                            "arguments": "",
                        })
                        if event.get("arguments") is not None:
                            slot["arguments"] = str(event.get("arguments") or "")
                        if event.get("name"):
                            slot["name"] = event["name"]
                        continue

                    if event_type == "response.output_item.done":
                        item = event.get("item") or {}
                        if isinstance(item, dict) and item.get("type") == "function_call":
                            key = _responses_tool_key(event, item)
                            slot = tool_calls.setdefault(key, {
                                "id": item.get("call_id") or item.get("id") or key,
                                "name": "",
                                "arguments": "",
                            })
                            if item.get("call_id") or item.get("id"):
                                slot["id"] = item.get("call_id") or item.get("id")
                            if item.get("name"):
                                slot["name"] = item["name"]
                            if item.get("arguments") is not None:
                                slot["arguments"] = str(item.get("arguments") or "")
                        continue

                    if event_type in {"response.completed", "response.done", "response.incomplete"}:
                        response = event.get("response") or {}
                        if isinstance(response, dict):
                            usage = response.get("usage") if isinstance(response.get("usage"), dict) else None
                            status = str(response.get("status") or "")
                            if status == "incomplete":
                                stop = "max_tokens"
                        continue

                    if event_type == "response.failed":
                        response = event.get("response") or {}
                        error = response.get("error") if isinstance(response, dict) else None
                        raise RuntimeError(f"openai-codex response failed: {error or event}")

        content: list[dict] = []
        if text_buf:
            content.append({"type": "text", "text": "".join(text_buf)})
        for key in sorted(tool_calls):
            block = _openai_tool_block(len(content), tool_calls[key], allow_incomplete=True)
            if block is not None:
                content.append(block)
        if any(block.get("type") == "tool_use" for block in content):
            stop = "tool_use"

        yield TurnEnd(
            stop_reason=stop,
            message={"role": "assistant", "content": content},
            usage=usage,
        )

    def _build_body(self, messages, tools, system):
        body: dict = {
            "model": self.model,
            "store": False,
            "stream": True,
            "instructions": system,
            "input": _to_responses_input(messages),
            "text": {"verbosity": "low"},
            "include": ["reasoning.encrypted_content"],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }
        effort = self._reasoning_effort or os.getenv("OPENAI_CODEX_REASONING_EFFORT")
        if effort:
            body["reasoning"] = {
                "effort": effort,
                "summary": os.getenv("OPENAI_CODEX_REASONING_SUMMARY", "auto"),
            }
        if tools:
            body["tools"] = [_to_responses_tool(t) for t in tools]
        return body


class GeminiProvider:
    """Gemini API adapter over REST/SSE.

    API keys use the Gemini Developer API. OAuth tokens use Vertex AI, which
    requires a Google Cloud project and location.
    """

    name = "gemini"
    context_window = 1_048_576

    def __init__(
        self,
        model: str = GEMINI_MODEL,
        max_tokens: int = GEMINI_MAX_TOKENS,
        api_key: str | None = None,
        auth_token: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
        base_url: str | None = None,
    ) -> None:
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not auth_token and not key:
            raise RuntimeError(
                "GeminiProvider needs either GEMINI_API_KEY or Google OAuth credentials "
                "(`python -m crypt login --provider gemini`)."
            )
        self.model = model.removeprefix("models/")
        self._api_key = key
        self._auth_token = auth_token
        self._project_id = project_id or os.getenv("GEMINI_PROJECT_ID") or ""
        self._location = location or os.getenv("GEMINI_LOCATION") or GEMINI_VERTEX_LOCATION
        self._max_tokens = max_tokens
        self._base_url = (base_url or os.getenv("GEMINI_BASE_URL") or GEMINI_BASE_URL).rstrip("/")
        self._http = httpx.Client(timeout=httpx.Timeout(10.0, read=240.0))
        atexit.register(self.close)

    @property
    def is_oauth(self) -> bool:
        return bool(self._auth_token)

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass

    def stream_turn(self, messages, tools, system):
        body = self._build_body(messages, tools, system)
        url = self._stream_url()
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
            if self._project_id:
                headers["x-goog-user-project"] = self._project_id
        elif self._api_key:
            headers["x-goog-api-key"] = self._api_key

        text_buf: list[str] = []
        tool_calls: list[dict] = []
        usage: dict | None = None
        stop = "end_turn"

        with self._http.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                resp.read()
                raise RuntimeError(_gemini_http_error(resp, oauth=bool(self._auth_token)))
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    data = _parse_data_sse(block)
                    if data is None:
                        continue
                    for ev in _process_gemini_response(data, text_buf, tool_calls):
                        yield ev
                    usage_meta = data.get("usageMetadata")
                    if isinstance(usage_meta, dict):
                        usage = {
                            "input_tokens": usage_meta.get("promptTokenCount", 0),
                            "output_tokens": usage_meta.get("candidatesTokenCount", 0),
                            "total_tokens": usage_meta.get("totalTokenCount", 0),
                        }
                    reason = _gemini_finish_reason(data)
                    if reason == "MAX_TOKENS":
                        stop = "max_tokens"

        content: list[dict] = []
        if text_buf:
            content.append({"type": "text", "text": "".join(text_buf)})
        for idx, call in enumerate(tool_calls):
            name = str(call.get("name") or "")
            if not name:
                continue
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            content.append({
                "type": "tool_use",
                "id": f"gemini_call_{idx}",
                "name": name,
                "input": args,
            })
        if any(block.get("type") == "tool_use" for block in content):
            stop = "tool_use"

        yield TurnEnd(
            stop_reason=stop,
            message={"role": "assistant", "content": content},
            usage=usage,
        )

    def _build_body(self, messages, tools, system):
        body: dict = {
            "contents": _to_gemini_contents(messages),
            "generationConfig": {
                "maxOutputTokens": self._max_tokens,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            declarations = [_to_gemini_function(tool) for tool in tools]
            body["tools"] = [{"functionDeclarations": declarations}]
            body["toolConfig"] = {
                "functionCallingConfig": {"mode": "AUTO"},
            }
        return body

    def _stream_url(self) -> str:
        model = self.model.removeprefix("publishers/google/models/").removeprefix("models/")
        if self._auth_token and self._project_id:
            location = self._location or GEMINI_VERTEX_LOCATION
            host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
            return (
                f"https://{host}/v1/projects/{self._project_id}/locations/{location}"
                f"/publishers/google/models/{model}:streamGenerateContent?alt=sse"
            )
        api_model = self.model if self.model.startswith("models/") else f"models/{self.model}"
        return f"{self._base_url}/{api_model}:streamGenerateContent?alt=sse"


def _codex_responses_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/codex/responses"):
        return normalized
    if normalized.endswith("/codex"):
        return f"{normalized}/responses"
    return f"{normalized}/codex/responses"


def _responses_tool_key(event: dict, item: dict) -> str:
    for name in ("item_id", "id", "call_id", "output_index"):
        value = item.get(name) or event.get(name)
        if value is not None:
            return str(value)
    return str(len(event))


def _openai_tool_block(
    idx: int,
    slot: dict,
    *,
    allow_incomplete: bool = False,
) -> dict | None:
    name = slot.get("name") or ""
    if not name:
        return None
    raw = slot.get("arguments") or ""
    if not raw and not allow_incomplete:
        return None
    try:
        args_obj = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        if not allow_incomplete:
            return None
        args_obj = {}
    if not isinstance(args_obj, dict):
        args_obj = {}
    return {
        "type": "tool_use",
        "id": slot.get("id") or f"call_{idx}",
        "name": name,
        "input": args_obj,
    }


def _to_responses_tool(tool: dict) -> dict:
    schema = dict(tool.get("input_schema") or tool.get("schema") or {})
    return {
        "type": "function",
        "name": str(tool.get("name", "")),
        "description": str(tool.get("description", "")),
        "parameters": schema,
    }


def _to_responses_input(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            out.append({
                "role": role,
                "content": [_responses_text_block(role, content)],
            })
            continue
        if not isinstance(content, list):
            continue

        text_parts: list[str] = []
        assistant_items: list[dict] = []
        tool_outputs: list[dict] = []

        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(str(block.get("text", "")))
            elif btype == "tool_use":
                assistant_items.append({
                    "type": "function_call",
                    "call_id": str(block.get("id", "")),
                    "name": str(block.get("name", "")),
                    "arguments": json.dumps(block.get("input") or {}),
                })
            elif btype == "tool_result":
                inner = block.get("content")
                if isinstance(inner, list):
                    inner = "".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in inner
                    )
                tool_outputs.append({
                    "type": "function_call_output",
                    "call_id": str(block.get("tool_use_id", "")),
                    "output": str(inner) if inner is not None else "",
                })
            elif btype == "thinking":
                continue

        text = "".join(text_parts)
        if role == "assistant":
            if text:
                out.append({
                    "role": "assistant",
                    "content": [_responses_text_block("assistant", text)],
                })
            out.extend(assistant_items)
        elif role == "user":
            if text:
                out.append({
                    "role": "user",
                    "content": [_responses_text_block("user", text)],
                })
            out.extend(tool_outputs)
    return out


def _responses_text_block(role: str | None, text: str) -> dict:
    return {
        "type": "output_text" if role == "assistant" else "input_text",
        "text": text,
    }


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """Convert internal Anthropic-style messages to OpenAI Chat Completions
    format. Tool results become role=tool messages; assistant tool_use
    blocks become role=assistant with a tool_calls array."""
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            continue

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        # Tool results live on user messages but become their own openai
        # messages. We collect them and emit after the user's text (if any).
        deferred_results: list[dict] = []

        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(str(block.get("text", "")))
            elif btype == "tool_use":
                args = block.get("input") or {}
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(args),
                    },
                })
            elif btype == "tool_result":
                inner = block.get("content")
                if isinstance(inner, list):
                    inner = "".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in inner
                    )
                deferred_results.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": str(inner) if inner is not None else "",
                })
            elif btype == "thinking":
                # OpenAI's classic chat API has no thinking surface.
                # o-series handles its own internal reasoning. Drop.
                continue

        if role == "assistant":
            item: dict = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                item["tool_calls"] = tool_calls
            out.append(item)
        elif role == "user":
            if text_parts:
                out.append({"role": "user", "content": "".join(text_parts)})
            out.extend(deferred_results)

    return out


def _parse_data_sse(block: str) -> dict | None:
    data_parts: list[str] = []
    for line in block.splitlines():
        if line.startswith("data:"):
            data_parts.append(line[5:].lstrip())
    if not data_parts:
        return None
    payload = "\n".join(data_parts).strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _process_gemini_response(data: dict, text_buf: list[str], tool_calls: list[dict]):
    candidates = data.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") if isinstance(candidate, dict) else None
        parts = (content or {}).get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if text:
                text = str(text)
                text_buf.append(text)
                yield TextDelta(text)
            call = part.get("functionCall") or part.get("function_call")
            if isinstance(call, dict):
                tool_calls.append(call)
                yield ToolUseProgress(
                    name=str(call.get("name") or ""),
                    call_id=f"gemini_call_{len(tool_calls) - 1}",
                    argument_chars=len(json.dumps(call.get("args") or {})),
                    partial_json=json.dumps(call.get("args") or {}),
                )


def _gemini_finish_reason(data: dict) -> str:
    candidates = data.get("candidates") or []
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("finishReason"):
            return str(candidate.get("finishReason") or "")
    return ""


def _gemini_http_error(resp: httpx.Response, *, oauth: bool) -> str:
    text = resp.text or ""
    message = text
    reason = ""
    try:
        data = resp.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            message = str(err.get("message") or message)
            details = err.get("details")
            if isinstance(details, list):
                for detail in details:
                    if isinstance(detail, dict) and detail.get("reason"):
                        reason = str(detail["reason"])
                        break

    if oauth and (
        resp.status_code in {401, 403}
        or reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT"
        or "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in text
    ):
        return (
            f"gemini OAuth HTTP {resp.status_code}: {message}. "
            "Gemini OAuth is routed through Vertex AI, so refresh the browser token with "
            "`python -m crypt login --provider gemini`, set GEMINI_PROJECT_ID to a Google Cloud "
            "project with Vertex AI enabled, and set GEMINI_LOCATION if the model is not in "
            f"{GEMINI_VERTEX_LOCATION}. For the Gemini Developer API path, use GEMINI_API_KEY."
        )

    body = text[:1000] if text else message
    return f"gemini HTTP {resp.status_code}: {body}"


def _to_gemini_contents(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    tool_names: dict[str, str] = {}
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            out.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]})
            continue
        if not isinstance(content, list):
            continue
        parts: list[dict] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append({"text": str(block.get("text", ""))})
            elif btype == "tool_use":
                call_id = str(block.get("id") or "")
                name = str(block.get("name") or "")
                if call_id:
                    tool_names[call_id] = name
                parts.append({
                    "functionCall": {
                        "name": name,
                        "args": block.get("input") if isinstance(block.get("input"), dict) else {},
                    },
                })
            elif btype == "tool_result":
                inner = block.get("content")
                if isinstance(inner, list):
                    inner = "".join(
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in inner
                    )
                tool_id = str(block.get("tool_use_id") or "")
                name = tool_names.get(tool_id) or str(block.get("name") or "tool_result")
                parts.append({
                    "functionResponse": {
                        "name": name,
                        "response": {"result": str(inner) if inner is not None else ""},
                    },
                })
            elif btype == "thinking":
                continue
        if parts:
            out.append({"role": "model" if role == "assistant" else "user", "parts": parts})
    return out or [{"role": "user", "parts": [{"text": ""}]}]


def _to_gemini_function(tool: dict) -> dict:
    return {
        "name": str(tool.get("name", "")),
        "description": str(tool.get("description", "")),
        "parameters": _to_gemini_schema(tool.get("input_schema") or tool.get("schema") or {}),
    }


def _to_gemini_schema(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return {"type": "OBJECT"}
    out: dict = {}
    for key, value in schema.items():
        if key in {"additionalProperties", "$schema"}:
            continue
        if key == "type" and isinstance(value, str):
            out[key] = value.upper()
        elif key == "properties" and isinstance(value, dict):
            out[key] = {
                str(name): _to_gemini_schema(sub if isinstance(sub, dict) else {})
                for name, sub in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            out[key] = _to_gemini_schema(value)
        elif key in {"required", "enum", "description", "format", "nullable"}:
            out[key] = value
        elif isinstance(value, dict):
            out[key] = _to_gemini_schema(value)
    return out or {"type": "OBJECT"}


class OllamaProvider:
    """Ollama via the official Anthropic SDK.

    Ollama natively serves Anthropic's /v1/messages API, which is how
    Claude Code talks to it. We use the `anthropic` SDK with `base_url`
    pointed at Ollama so we inherit the SDK's:

      - Battle-tested SSE streaming + event parsing.
      - 2x exponential-backoff retry on connection / 5xx errors.
      - Sane default timeouts (10 minutes total, configurable via env).
      - Tool-use semantics (content_block_start + input_json_delta + stop).

    Auth: Authorization: Bearer <token>. Local Ollama accepts the literal
    string ``ollama``; cloud Ollama wants a real key from $OLLAMA_API_KEY.

    Streaming events from the SDK are Pydantic models; we ``model_dump()``
    them into plain dicts and feed through Crypt's shared ``_process_event``
    so the rest of the harness sees the same internal events as on the
    Anthropic path (TextDelta, ThinkingDelta, ToolUseProgress, ToolUseReady,
    TurnEnd).
    """

    name = "ollama"
    context_window = 256_000
    is_oauth = False

    def __init__(
        self,
        model: str = OLLAMA_MODEL,
        host: str | None = None,
        think: bool = True,  # kept for signature compat with /model switcher
        thinking_budget: int | None = None,
    ) -> None:
        from anthropic import Anthropic

        self._base_url = _normalize_ollama_host(
            host or os.getenv("OLLAMA_HOST") or "http://localhost:11434"
        )
        api_key = os.getenv("OLLAMA_API_KEY") or "ollama"
        try:
            timeout = float(os.getenv("OLLAMA_TIMEOUT", "600"))
        except ValueError:
            timeout = 600.0
        try:
            # Bumped 8192 → 16384 so a single write_file with a 300+ line
            # artifact doesn't truncate and force the agent to retry.
            self._max_tokens = int(os.getenv("OLLAMA_MAX_TOKENS", "16384"))
        except ValueError:
            self._max_tokens = 16384
        # Thinking-capable models (Qwen3, Kimi K2, GLM, DeepSeek) emit a
        # `thinking` content block when this is configured. Set to 0 in
        # the env to disable for non-thinking models.
        if thinking_budget is None:
            try:
                self._thinking_budget = int(os.getenv("OLLAMA_THINKING_BUDGET", "0"))
            except ValueError:
                self._thinking_budget = 0
        else:
            self._thinking_budget = max(0, int(thinking_budget))
        # Anthropic's API rejects budget >= max_tokens; leave room for the
        # actual response.
        if self._thinking_budget >= self._max_tokens:
            self._thinking_budget = max(0, self._max_tokens - 2048)

        self._client = Anthropic(
            api_key=api_key,
            base_url=self._base_url,
            timeout=timeout,
        )
        self.model = model
        self.host = host
        self._think = think

    def stream_turn(self, messages, tools, system):
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": messages,
            "stream": True,
        }
        if self._thinking_budget > 0 and self._think:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self._thinking_budget,
            }
        if tools:
            # Tools use Anthropic's native shape — Crypt's tool registry
            # already produces this; no translation needed.
            kwargs["tools"] = [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool["input_schema"],
                }
                for tool in tools
            ]

        content_blocks: list[dict | None] = []
        usage: dict = {"input_tokens": 0, "output_tokens": 0}
        stop_reason = "end_turn"

        try:
            stream = self._client.messages.create(**kwargs)
            for event in stream:
                event_type = getattr(event, "type", None)
                if not event_type:
                    continue
                # SDK events are Pydantic models; convert to dicts so the
                # shared event processor can read them like raw SSE payloads.
                data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
                for ev in _process_event(event_type, data, content_blocks, usage):
                    if isinstance(ev, _StopReason):
                        stop_reason = ev.value
                    else:
                        yield ev
        except Exception as e:
            if _is_ollama_auth_error(e):
                raise RuntimeError(_ollama_auth_help(self._base_url)) from e
            raise

        yield TurnEnd(
            stop_reason=stop_reason,
            message=_finalized_assistant_message(content_blocks),
            usage=usage,
        )


def _normalize_ollama_host(host: str) -> str:
    """Coerce common host strings into a real client URL.

    Users (and Ollama itself) sometimes set OLLAMA_HOST to a listening
    address like ``0.0.0.0`` or a bare ``localhost``. httpx needs a real
    base URL; this fills in the gaps without surprising the user.
    """
    host = host.strip().rstrip("/")
    if not host:
        return "http://localhost:11434"
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    # 0.0.0.0 is a listening address, not a client target.
    host = host.replace("//0.0.0.0", "//localhost")
    # Add Ollama's default port for local-style hosts that omit it.
    # urlparse's port attribute returns None when no explicit port is set.
    import urllib.parse as _u
    parsed = _u.urlparse(host)
    if parsed.port is None and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        host = f"{parsed.scheme}://{parsed.hostname}:11434{parsed.path or ''}"
    return host


def _is_ollama_auth_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if name in {"authenticationerror", "permissiondeniederror"}:
        return True
    return any(
        marker in text
        for marker in (
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "invalid api key",
            "authentication",
            "permission denied",
        )
    )


def _ollama_auth_help(base_url: str) -> str:
    from .settings import is_ollama_cloud_host

    if is_ollama_cloud_host(base_url):
        return (
            "Ollama authentication failed for https://ollama.com. "
            "Ollama does not use Anthropic OAuth; set OLLAMA_API_KEY to an "
            "Ollama Cloud API key, or use --ollama-host http://localhost:11434 "
            "for local Ollama."
        )
    return (
        "Ollama authentication failed. Ollama does not use Anthropic OAuth. "
        "Set OLLAMA_API_KEY only if this Ollama host requires a bearer token; "
        "local Ollama normally uses http://localhost:11434 without a key."
    )


def _to_openai_tool(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }
