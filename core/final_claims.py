"""Guard final assistant claims against runtime evidence."""
from __future__ import annotations

import re

from . import evidence


_COMPLETION_RE = re.compile(
    r"\b(done|completed|fixed|implemented|all tests passed|tests passed|verified|working|ready)\b",
    re.I,
)
_VERIFICATION_WORD_RE = re.compile(r"\b(test|pytest|check|verified|verification|doctor|lint|typecheck)\b", re.I)
_NOTE = (
    "Verification note: no runtime evidence recorded for tests or checks; "
    "treat this result as unverified."
)


def needs_guard(text: str) -> bool:
    text = str(text or "")
    if not _COMPLETION_RE.search(text):
        return False
    return not evidence.has_any_verification()


def guard_text(text: str) -> tuple[str, str]:
    text = str(text or "")
    if not needs_guard(text):
        return text, ""
    if _NOTE in text:
        return text, _NOTE
    sep = "\n\n" if text.strip() else ""
    return f"{text.rstrip()}{sep}{_NOTE}", _NOTE


def apply_to_message(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        guarded, note = guard_text(content)
        message["content"] = guarded
        return note
    if not isinstance(content, list):
        return ""
    text_blocks = [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    if not text_blocks:
        return ""
    original = "\n".join(str(block.get("text", "")) for block in text_blocks)
    guarded, note = guard_text(original)
    if not note:
        return ""
    text_blocks[-1]["text"] = str(text_blocks[-1].get("text", "")).rstrip() + "\n\n" + _NOTE
    return note


def verification_summary_for_final() -> str:
    results = evidence.latest_verifications()
    if not results:
        return "No verification evidence recorded."
    latest = results[-1]
    if latest.commands:
        return f"{latest.status}: " + "; ".join(latest.commands)
    return latest.status


def mentions_verification(text: str) -> bool:
    return bool(_VERIFICATION_WORD_RE.search(str(text or "")))
