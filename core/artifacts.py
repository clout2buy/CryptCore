"""Artifact creation policy helpers for the agent loop."""
from __future__ import annotations

import re


_ARTIFACT_ACTION_RE = re.compile(
    r"\b(make|create|build|generate|generated|write|code|craft|produce|scaffold|implement)\b",
    re.I,
)
_ARTIFACT_TARGET_RE = re.compile(
    r"\b(html|web\s*page|website|site|app|component|script|program|file|css|javascript|js|typescript|ts|python|py|json|markdown|md|readme|dashboard|game|animation|animated|landing\s*page)\b",
    re.I,
)
_FENCED_ARTIFACT_RE = re.compile(
    r"```(?:[A-Za-z0-9_+.-]+)?\s*\n[\s\S]{250,}?```",
    re.M,
)
_FENCED_ARTIFACT_START_RE = re.compile(
    r"```(?:html|css|javascript|js|typescript|ts|python|py|json|markdown|md)\b",
    re.I,
)
_HTML_ARTIFACT_RE = re.compile(r"<!DOCTYPE\s+html|<html(?:\s|>)", re.I)


def extract_text(message: dict) -> str:
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def creation_requested(messages: list[dict]) -> bool:
    text = _last_real_user_text(messages)
    return bool(text and _ARTIFACT_ACTION_RE.search(text) and _ARTIFACT_TARGET_RE.search(text))


def should_retry_text_only(messages: list[dict], assistant_msg: dict) -> bool:
    if not creation_requested(messages):
        return False
    text = extract_text(assistant_msg)
    if not text:
        return False
    return bool(
        looks_like_artifact_start(text)
        or _FENCED_ARTIFACT_RE.search(text)
        or _HTML_ARTIFACT_RE.search(text)
    )


def should_retry_empty(messages: list[dict], assistant_msg: dict) -> bool:
    if not creation_requested(messages):
        return False
    if extract_text(assistant_msg):
        return False
    return not _has_tool_use(assistant_msg)


def tool_retry_message(messages: list[dict]) -> dict:
    request = _last_real_user_text(messages) or _last_textual_user_message(messages)
    wants_open = bool(re.search(r"\b(open|launch|show)\b", request, re.I))
    open_instruction = (
        " After write_file succeeds, call open_file for the generated file."
        if wants_open
        else ""
    )
    return {
        "role": "user",
        "content": [{
            "type": "text",
            "text": (
                "Crypt harness correction: you pasted the artifact in chat instead of using tools. "
                "Do not paste the code again. Call write_file with a sensible filename and the full "
                f"artifact content.{open_instruction} Keep narration minimal."
            ),
        }],
    }


def empty_retry_message(messages: list[dict]) -> dict:
    request = _last_real_user_text(messages) or _last_textual_user_message(messages)
    wants_open = bool(re.search(r"\b(open|launch|show)\b", request, re.I))
    open_instruction = (
        " After write_file succeeds, call open_file for the generated file."
        if wants_open
        else ""
    )
    return {
        "role": "user",
        "content": [{
            "type": "text",
            "text": (
                "Crypt harness correction: your previous response ended empty after hidden reasoning. "
                "Do not return an empty answer. Your next response must immediately call write_file "
                "with a sensible filename and the complete artifact content for "
                f"the user's request: {request!r}.{open_instruction} Keep narration minimal."
            ),
        }],
    }


def reasoning_stall_retry_message(messages: list[dict]) -> dict:
    request = _last_real_user_text(messages) or _last_textual_user_message(messages)
    wants_open = bool(re.search(r"\b(open|launch|show)\b", request, re.I))
    open_instruction = (
        " After write_file succeeds, call open_file for the generated file."
        if wants_open
        else ""
    )
    return {
        "role": "user",
        "content": [{
            "type": "text",
            "text": (
                "Crypt harness correction: your previous attempt spent too long in hidden reasoning "
                "without emitting text or a tool call. Stop planning internally. Your next response must "
                "immediately call write_file with a sensible filename and the full artifact content for "
                f"the user's request: {request!r}.{open_instruction} Keep narration minimal."
            ),
        }],
    }


def fast_lane_system_guidance(messages: list[dict]) -> str:
    request = _last_real_user_text(messages) or _last_textual_user_message(messages)
    return (
        "# Current Turn Constraint\n"
        "The user asked Crypt to create a file/artifact. Your next assistant message "
        "must contain a write_file or edit_file tool call as the first substantive action. "
        "Do not call todos, present_plan, ask_user, or spawn_agent first. Do not return an "
        "empty response. Do not paste the artifact in chat. If the artifact is large, write "
        "a complete smaller version instead of planning silently.\n"
        f"Requested artifact: {request!r}"
    )


def looks_like_artifact_start(text: str) -> bool:
    if not text:
        return False
    if _HTML_ARTIFACT_RE.search(text):
        return True
    if _FENCED_ARTIFACT_START_RE.search(text):
        return True
    return bool(len(text) >= 600 and re.search(r"```\w*", text))


def _has_tool_use(msg: dict) -> bool:
    return any(
        isinstance(block, dict) and block.get("type") == "tool_use"
        for block in msg.get("content", [])
    )


def successful_tool_names_since_last_request(messages: list[dict]) -> set[str]:
    start = _last_real_user_index(messages)
    tool_names: dict[str, str] = {}
    successes: set[str] = set()
    for msg in messages[start + 1:]:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        if msg.get("role") == "assistant":
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("id")
                ):
                    tool_names[str(block["id"])] = str(block.get("name", ""))
        elif msg.get("role") == "user":
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and not block.get("is_error")
                ):
                    name = tool_names.get(str(block.get("tool_use_id", "")))
                    if name:
                        successes.add(name)
    return successes


def _last_textual_user_message(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        text = extract_text(msg)
        if text:
            return text
    return ""


def _last_real_user_text(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        text = extract_text(msg)
        if not text or text.startswith("Crypt harness correction:"):
            continue
        content = msg.get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        ):
            continue
        return text
    return ""


def _last_real_user_index(messages: list[dict]) -> int:
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") != "user":
            continue
        text = extract_text(msg)
        if not text or text.startswith("Crypt harness correction:"):
            continue
        content = msg.get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        ):
            continue
        return i
    return 0
