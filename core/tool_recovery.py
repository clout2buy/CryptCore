"""Recovery policy for failed tool-call turns.

Some model failures are not real blockers; they are bad tool arguments. The
harness should correct those once instead of accepting a prose "I can continue"
answer that leaves the repo half-edited.
"""
from __future__ import annotations

import re


_RECOVERABLE_RE = re.compile(
    r"("
    r"schema validation failed|missing required input|expected a non-empty|no edits provided|"
    r"fix the arguments|Recovery:|no match for|matches for|file changed since Crypt read it|"
    r"read-before-edit invariant|FileNotFoundError|unsupported media type|was not found on PATH|"
    r"not installed on this Windows shell|\[hint:|command timed out"
    r")",
    re.I,
)
_HARD_STOP_RE = re.compile(
    r"^(denied by user|PermissionError:|blocked by runtime policy|approval required)",
    re.I,
)
_RECOVERABLE_TOOLS = {
    "bash",
    "bash_start",
    "edit_file",
    "glob",
    "grep",
    "list_files",
    "multi_edit",
    "open_file",
    "read_file",
    "read_media",
    "write_file",
}
_SPIRAL_STOP_TOOLS = {"edit_file", "multi_edit", "write_file"}
_SPIRAL_STOP_THRESHOLD = 3


def should_retry_after_tool_failure(messages: list[dict], assistant_msg: dict) -> bool:
    """True when the model gave prose after recoverable tool validation errors."""
    if _has_tool_use(assistant_msg):
        return False
    failed = recoverable_failures_before_final(messages)
    if not failed:
        return False
    final_text = _extract_text(assistant_msg)
    if not final_text.strip():
        return True
    # After recoverable arg failures, any final prose without tool use is too
    # early. It may be a promise, apology, or partial-progress summary.
    return True


def recovery_message(messages: list[dict]) -> dict:
    failures = recoverable_failures_before_final(messages)
    lines = []
    for item in failures[:4]:
        name = item.get("tool_name") or "tool"
        content = str(item.get("content") or "")
        lines.append(f"- {name}: {_one_line(content, 220)}")
    detail = "\n".join(lines) if lines else "- recoverable tool argument failure"
    return {
        "role": "user",
        "content": [{
            "type": "text",
            "text": (
                "Crypt harness correction: the previous tool calls failed because their arguments were invalid, "
                "not because the task is impossible. Do not stop with a partial-progress summary. "
                "Your next response must either retry the failed edit/write with valid non-empty arguments, "
                "or use read_file/list_files/grep to recover exact context before retrying. "
                "If read-before-edit says only a partial range was read, call read_file for that path with no "
                "offset or limit exactly once; do not repeat the same partial slice. "
                "If the chosen implementation is too large, split it into the next smallest concrete file edit. "
                "Recent recoverable failures:\n"
                f"{detail}"
            ),
        }],
    }


def should_stop_after_failure_spiral(messages: list[dict]) -> bool:
    """True when the same task keeps failing tool invariants.

    Recovery nudges are useful once. After several invalid edit/write attempts,
    continuing usually burns turns and context without improving the result.
    """
    failures = recent_recoverable_failures(messages, tools=_SPIRAL_STOP_TOOLS)
    return len(failures) >= _SPIRAL_STOP_THRESHOLD


def spiral_stop_message(messages: list[dict]) -> dict:
    failures = recent_recoverable_failures(messages, tools=_SPIRAL_STOP_TOOLS)
    lines = []
    for item in failures[-_SPIRAL_STOP_THRESHOLD:]:
        name = item.get("tool_name") or "tool"
        content = str(item.get("content") or "")
        lines.append(f"- {name}: {_one_line(content, 180)}")
    detail = "\n".join(lines) if lines else "- repeated edit/write tool failures"
    return {
        "role": "assistant",
        "content": [{
            "type": "text",
            "text": (
                "I stopped before retrying the same failing tool path again.\n\n"
                "The recent edit/write attempts are failing validation or read-before-edit checks, "
                "so another blind call would likely waste more turns. The right next move is to read "
                "the full target file once, make one concrete non-empty edit, and then verify the result.\n\n"
                f"Recent failures:\n{detail}"
            ),
        }],
    }


def recent_recoverable_failures(
    messages: list[dict],
    *,
    tools: set[str] | frozenset[str] | None = None,
    limit: int = 8,
) -> list[dict]:
    names_by_id: dict[str, str] = {}
    failures: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                call_id = str(block.get("id") or "")
                if call_id:
                    names_by_id[call_id] = str(block.get("name") or "")
            continue
        if role != "user" or not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if not block.get("is_error"):
                continue
            text = str(block.get("content") or "")
            if _HARD_STOP_RE.search(text) or not _RECOVERABLE_RE.search(text):
                continue
            tool_name = names_by_id.get(str(block.get("tool_use_id") or ""), "tool")
            if tools is not None and tool_name not in tools:
                continue
            failures.append({
                "tool_use_id": block.get("tool_use_id"),
                "tool_name": tool_name,
                "content": text,
            })
    return failures[-max(1, limit):]


def recoverable_failures_before_final(messages: list[dict]) -> list[dict]:
    if len(messages) < 2:
        return []
    # messages[-1] is usually the final assistant prose by the time this is
    # checked. Walk backward to the nearest tool_result user message.
    for idx in range(len(messages) - 2, -1, -1):
        msg = messages[idx]
        if msg.get("role") == "assistant":
            # Stop at previous assistant turn; older failures have already had
            # a chance to influence a model response.
            return []
        content = msg.get("content")
        if msg.get("role") != "user" or not isinstance(content, list):
            continue
        if not any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
            continue
        names = _tool_names_from_previous_assistant(messages, idx)
        out: list[dict] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if not block.get("is_error"):
                continue
            text = str(block.get("content") or "")
            if _HARD_STOP_RE.search(text):
                continue
            if not _RECOVERABLE_RE.search(text):
                continue
            tool_name = names.get(str(block.get("tool_use_id") or ""))
            if tool_name and tool_name not in _RECOVERABLE_TOOLS:
                continue
            out.append({
                "tool_use_id": block.get("tool_use_id"),
                "tool_name": tool_name or "tool",
                "content": text,
            })
        return out
    return []


def _tool_names_from_previous_assistant(messages: list[dict], user_idx: int) -> dict[str, str]:
    for idx in range(user_idx - 1, -1, -1):
        msg = messages[idx]
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            return {}
        return {
            str(block.get("id")): str(block.get("name") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id")
        }
    return {}


def _has_tool_use(message: dict) -> bool:
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_use"
        for block in content
    )


def _extract_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def _one_line(text: str, limit: int) -> str:
    text = str(text or "").replace("\n", " | ").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."
