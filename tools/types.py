from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    permission: str
    run: Callable[[dict], Any]
    prompt: str = ""
    priority: int = 100
    summary: Callable[[dict], str] | None = None
    before_prompt: Callable[[], None] | None = None
    reset: Callable[[], None] | None = None
    available_in_subagent: bool = True
    quiet: bool = False
    # Optional per-call safety classifier. Returns one of:
    #   "safe"   - read-only / harmless; auto-approve in every mode
    #   "danger" - destructive; always confirm with a warning, even in yolo
    #   None or "ask" - default; use the tool's `permission` field
    # Letting tools self-classify keeps the registry generic.
    classify: Callable[[dict], str | None] | None = None
    # True only for deterministic read-only tools that can safely execute
    # beside each other when the model emits multiple tool calls in one turn.
    parallel_safe: bool = False
    # Optional preview generator. Returns text to show the user BEFORE the
    # approval prompt — typically a unified diff for edit/write tools so
    # the user sees what's about to change instead of approving a blob.
    # Should be cheap and side-effect-free. May raise; raises are swallowed
    # by the dispatcher so the user still sees the standard prompt.
    preview: Callable[[dict], str] | None = None
    # Optional semantic validation that the simple JSON-schema checker cannot
    # express, such as "old+new or non-empty edits[]". Return a list of
    # human-readable errors; dispatch surfaces them before approvals.
    validate: Callable[[dict], list[str]] | None = None
