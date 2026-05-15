"""Recovery advice for failed tool calls."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_ERROR_CHARS = 900


@dataclass(frozen=True)
class RecoveryAdvice:
    category: str
    hint: str
    retry_tool: str = ""


def advise(tool_name: str, args: dict | None, message: str) -> RecoveryAdvice | None:
    lower = str(message or "").lower()
    name = str(tool_name or "")
    if name in {"edit_file", "multi_edit", "write_file"}:
        path = _path_arg(args or {})
        if "read-before-edit" in lower or "file changed" in lower:
            return RecoveryAdvice(
                "stale-file-context",
                f"read {path or 'the target file'} again, then retry the edit against the newest exact text",
                "read_file",
            )
        if "no match" in lower or "matches for" in lower:
            return RecoveryAdvice(
                "edit-context-mismatch",
                "retry once with a smaller unique replacement or a longer old string with surrounding lines",
                "read_file",
            )
    if name in {"read_file", "open_file", "read_media", "grep", "glob", "list_files"}:
        if "filenotfounderror" in lower or "no such file" in lower:
            return RecoveryAdvice(
                "missing-path",
                "list or glob the parent directory, then retry with an existing path",
                "list_files",
            )
    if name in {"bash", "bash_start"}:
        if "timed out" in lower:
            return RecoveryAdvice("shell-timeout", "use bash_start for long-running commands, then bash_poll", "bash_start")
        if "not recognized" in lower or "was not found" in lower:
            return RecoveryAdvice("missing-command", "check the command with Get-Command or use the PowerShell equivalent")
    if name.startswith("web_"):
        if "timeout" in lower or "connection" in lower:
            return RecoveryAdvice("network", "retry with a narrower query or state that network verification failed")
    return None


def format_hint(tool_name: str, args: dict | None, message: str) -> str:
    advice = advise(tool_name, args, message)
    if not advice:
        return ""
    return f"\nRecovery: {advice.hint}."


def compact_failure(message: str, *, limit: int = MAX_ERROR_CHARS) -> str:
    clean = " ".join(str(message or "").split())
    if len(clean) <= limit:
        return clean
    head = clean[: max(0, limit - 80)].rstrip()
    return f"{head}... [tool error truncated; keep the recovery step and avoid dumping raw logs]"


def should_retry_after_tool_failure(messages: list[dict], assistant_message: dict) -> bool:
    if _has_tool_use(assistant_message):
        return False
    if should_stop_after_failure_spiral(messages):
        return False
    failure = _last_recoverable_failure(messages)
    if failure is None:
        return False
    text = _assistant_text(assistant_message).lower()
    if any(marker in text for marker in ("recovered", "completed", "done", "fixed")):
        return False
    return not text or any(
        marker in text
        for marker in ("partway", "can continue", "try something else", "later", "failed", "unable", "could retry")
    )


def recovery_message(messages: list[dict]) -> dict:
    failure = _last_recoverable_failure(messages) or {}
    tool_name = str(failure.get("tool") or "tool")
    content = str(failure.get("content") or "")
    if tool_name in {"edit_file", "multi_edit", "write_file"}:
        detail = (
            "The previous tool calls failed because their arguments were invalid. "
            "Do not summarize or stop. retry the failed edit/write by first reading "
            "the exact current file context, then call the edit tool once with a "
            "non-empty concrete replacement."
        )
    elif tool_name in {"bash", "bash_start"}:
        detail = (
            "The previous bash tool call failed with a platform or command issue. "
            "Use the recovery hint, switch to PowerShell-compatible syntax when on "
            "Windows, and retry once with the corrected command."
        )
    else:
        detail = (
            "The previous tool call failed in a recoverable way. Use the recovery "
            "hint, adjust the arguments, and retry once instead of stopping."
        )
    hint = format_hint(tool_name, failure.get("input") if isinstance(failure.get("input"), dict) else {}, content)
    if hint:
        detail += f" {hint.strip()}"
    detail = f"Crypt harness correction: {detail}"
    return {"role": "user", "content": [{"type": "text", "text": detail}]}


def should_stop_after_failure_spiral(messages: list[dict]) -> bool:
    failures = [
        failure for failure in _failed_tool_results(messages)
        if failure.get("tool") in {"edit_file", "multi_edit", "write_file"}
        and _is_recoverable_failure(str(failure.get("content") or ""))
    ]
    return len(failures) >= 3


def spiral_stop_message(messages: list[dict]) -> dict:
    paths = [
        str((failure.get("input") or {}).get("path") or "")
        for failure in _failed_tool_results(messages)
        if isinstance(failure.get("input"), dict)
    ]
    path_text = f" Target path: {paths[-1]}." if paths and paths[-1] else ""
    text = (
        "Stopped repeated invalid edit arguments before wasting more turns. "
        "Recovery: read the full target file, identify the exact current text, "
        "then retry with one concrete non-empty edit."
        f"{path_text}"
    )
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _path_arg(args: dict) -> str:
    if not isinstance(args, dict):
        return ""
    if args.get("path"):
        return str(Path(str(args.get("path"))))
    changes = args.get("changes")
    if isinstance(changes, list) and changes and isinstance(changes[0], dict):
        return str(changes[0].get("path") or "")
    return ""


def _last_recoverable_failure(messages: list[dict]) -> dict | None:
    for failure in reversed(_failed_tool_results(messages)):
        if _is_recoverable_failure(str(failure.get("content") or "")):
            return failure
    return None


def _failed_tool_results(messages: list[dict]) -> list[dict]:
    uses = _tool_uses(messages)
    out: list[dict] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        for block in _content_blocks(message):
            if block.get("type") != "tool_result" or not block.get("is_error"):
                continue
            call_id = str(block.get("tool_use_id") or "")
            use = uses.get(call_id, {})
            out.append(
                {
                    "tool": str(use.get("name") or ""),
                    "input": use.get("input") if isinstance(use.get("input"), dict) else {},
                    "content": str(block.get("content") or ""),
                    "tool_use_id": call_id,
                }
            )
    return out


def _tool_uses(messages: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for block in _content_blocks(message):
            if block.get("type") == "tool_use":
                out[str(block.get("id") or "")] = block
    return out


def _content_blocks(message: dict) -> list[dict[str, Any]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _has_tool_use(message: dict) -> bool:
    return any(block.get("type") == "tool_use" for block in _content_blocks(message))


def _assistant_text(message: dict) -> str:
    parts: list[str] = []
    content = message.get("content")
    if isinstance(content, str):
        parts.append(content)
    for block in _content_blocks(message):
        if block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return " ".join(parts)


def _is_recoverable_failure(content: str) -> bool:
    lower = content.lower()
    return any(
        marker in lower
        for marker in (
            "schema validation failed",
            "expected a non-empty array",
            "read-before-edit",
            "file changed since",
            "no match",
            "[hint:",
            "not recognized",
            "was not found",
            "timed out",
        )
    )
