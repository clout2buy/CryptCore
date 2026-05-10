"""Conversation compaction.

Two layers:

* `compact_messages` — full summarisation of older history once the context
  is ~72% full. Cheap-to-resume, expensive-to-run.
* `micro_compact` — cheap, no-LLM elision of *individual* old tool_result
  bodies in long sessions. Triggered earlier (~50%). Mirrors Claude Code's
  microCompact policy: keep the assistant's reasoning, throw away the
  re-readable evidence.
"""
from __future__ import annotations

from .api import Provider, TextDelta, ThinkingDelta, TurnEnd


# Tools whose results can be safely elided once they're a few turns old:
# the model can re-run them if it needs the data again. Excludes tools
# whose result IS load-bearing semantic state (todos, plan, spawn_agent
# whose synthesized report is the entire value).
COMPACTABLE_TOOLS = frozenset({
    "read_file",
    "bash",
    "bash_poll",
    "grep",
    "glob",
    "list_files",
    "web_fetch",
    "web_search",
    "read_media",
    "git",
})

# Don't bother eliding small results — saves nothing, costs readability.
MICRO_COMPACT_MIN_BYTES = 4_000

# Leave the most recent N messages untouched so the model still has its
# fresh evidence in view.
MICRO_COMPACT_KEEP_RECENT = 6


COMPACT_SYSTEM = """You are Crypt's compaction engine. Produce durable continuation context only.
Do not call tools. Do not chat with the user. Preserve exact technical facts."""


COMPACT_PROMPT = """Create a precise continuation summary for this Crypt session.

Include:
1. User intent and explicit instructions.
2. Current task state and immediate next step.
3. Files read or edited, with important symbols and decisions.
4. Commands run and meaningful outputs or failures.
5. Errors, corrections, and approaches to avoid.
6. Pending todos or unresolved risks.
7. Durable user/project preferences that should be remembered.

Be dense, factual, and useful for resuming the work. Do not invent success.
"""


def rough_tokens(messages: list[dict]) -> int:
    chars = 0
    for msg in messages:
        chars += len(str(msg.get("role", "")))
        chars += len(str(msg.get("content", "")))
    return max(1, chars // 4)


def should_compact(messages: list[dict], context_window: int, pct: float = 0.72) -> bool:
    if len(messages) < 12:
        return False
    return rough_tokens(messages) >= int(context_window * pct)


def compact_messages(
    provider: Provider,
    messages: list[dict],
    keep_tail: int = 8,
) -> tuple[str, list[dict]]:
    if len(messages) <= keep_tail + 2:
        return "", messages

    tail = _safe_tail(messages, keep_tail)
    older = messages[: -len(tail)] if tail else messages
    prompt = {
        "role": "user",
        "content": [
            {"type": "text", "text": COMPACT_PROMPT},
            {"type": "text", "text": "\n\n<conversation>\n" + str(older) + "\n</conversation>"},
        ],
    }
    summary_parts: list[str] = []
    final: TurnEnd | None = None
    for event in provider.stream_turn([prompt], [], COMPACT_SYSTEM):
        if isinstance(event, TextDelta):
            summary_parts.append(event.text)
        elif isinstance(event, ThinkingDelta):
            continue
        elif isinstance(event, TurnEnd):
            final = event
    if final and not summary_parts:
        summary_parts.append(_extract_text(final.message))
    summary = "".join(summary_parts).strip()
    if not summary:
        raise RuntimeError("compaction produced no summary")
    compact_msg = {
        "role": "user",
        "content": (
            "<crypt_compaction_summary>\n"
            + summary
            + "\n</crypt_compaction_summary>\n\n"
            "Continue from this summary and the recent messages that follow."
        ),
    }
    return summary, [compact_msg, *tail]


def _safe_tail(messages: list[dict], keep_tail: int) -> list[dict]:
    """Trim from the front so the tail never starts with an orphaned
    tool_result (which would 400 against the API). When the tail begins
    with a USER tool_result, walk back to include the matching ASST
    tool_use as well — the pair has to travel together."""
    tail = messages[-keep_tail:] if keep_tail < len(messages) else list(messages)
    while tail and _is_tool_result_message(tail[0]) and keep_tail < len(messages):
        keep_tail += 1
        tail = messages[-keep_tail:]
    return tail


def micro_compact(
    messages: list[dict],
    *,
    keep_recent: int = MICRO_COMPACT_KEEP_RECENT,
    min_bytes: int = MICRO_COMPACT_MIN_BYTES,
    compactable: frozenset[str] = COMPACTABLE_TOOLS,
) -> int:
    """Mutate `messages` in place: replace large old tool_result bodies for
    re-runnable tools with a one-line marker. Cheap, no LLM call. Returns
    the number of blocks elided.

    Skips:
      - Anything within the last `keep_recent` messages.
      - Tool results smaller than `min_bytes`.
      - Tools not in `compactable` (their results carry irreplaceable state).
      - Already-elided results (idempotent).
    """
    if len(messages) <= keep_recent:
        return 0

    # Build tool_use_id -> tool_name index by walking assistant messages.
    tool_name_by_id: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_name_by_id[block.get("id", "")] = block.get("name", "")

    cutoff = len(messages) - keep_recent
    elided = 0
    for idx in range(cutoff):
        msg = messages[idx]
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                continue
            tool_name = tool_name_by_id.get(block.get("tool_use_id", ""), "")
            if tool_name not in compactable:
                continue
            body = block.get("content")
            body_text = _stringify_tool_result(body)
            if len(body_text) < min_bytes:
                continue
            if body_text.startswith("[old tool result elided"):
                continue
            block["content"] = (
                f"[old tool result elided ({len(body_text):,} chars). "
                f"Re-run {tool_name or 'the tool'} if you need the data again.]"
            )
            elided += 1
    return elided


def _stringify_tool_result(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Anthropic allows multimodal tool_result content blocks; flatten text
        # parts and approximate the rest by string length.
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content) if content is not None else ""


def _is_tool_result_message(message: dict) -> bool:
    if message.get("role") != "user" or not isinstance(message.get("content"), list):
        return False
    return any(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in message["content"]
    )


def _extract_text(message: dict) -> str:
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
