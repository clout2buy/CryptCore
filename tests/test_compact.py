"""Compaction — both micro and the orphan-safe tail trim.

The full-conversation compactor calls the LLM and isn't unit-tested
here; we test the deterministic pieces it relies on.
"""
from __future__ import annotations

from core import compact
from core import loop


def _block_pair(idx: int, body: str, name: str = "read_file"):
    tid = f"t{idx}"
    return [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": {}}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": body}
        ]},
    ]


def test_micro_compact_elides_old_large_results():
    msgs = [{"role": "user", "content": "go"}]
    for i in range(8):
        msgs.extend(_block_pair(i, "X" * 5000))

    elided = compact.micro_compact(msgs, keep_recent=4, min_bytes=1000)
    assert elided > 0
    # The very last results stay full-fat.
    last_results = [
        b["content"]
        for m in msgs[-4:]
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if isinstance(b, dict) and b.get("type") == "tool_result"
    ]
    assert all(len(s) == 5000 for s in last_results)


def test_micro_compact_idempotent():
    msgs = [{"role": "user", "content": "go"}]
    for i in range(8):
        msgs.extend(_block_pair(i, "X" * 5000))
    first = compact.micro_compact(msgs, keep_recent=4, min_bytes=1000)
    second = compact.micro_compact(msgs, keep_recent=4, min_bytes=1000)
    assert first > 0 and second == 0


def test_micro_compact_skips_non_compactable_tools():
    msgs = [
        {"role": "user", "content": "go"},
        *_block_pair(0, "irreplaceable report " * 500, name="spawn_agent"),
        *[{"role": "user", "content": f"chat {i}"} for i in range(10)],
    ]
    elided = compact.micro_compact(msgs, keep_recent=4, min_bytes=1000)
    assert elided == 0


def test_micro_compact_skips_small_results():
    msgs = [{"role": "user", "content": "go"}]
    for i in range(8):
        msgs.extend(_block_pair(i, "tiny"))
    elided = compact.micro_compact(msgs, keep_recent=4, min_bytes=1000)
    assert elided == 0


def test_safe_tail_avoids_orphan_tool_result():
    msgs = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": [{"type": "text", "text": "thinking"}]},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
    ]
    tail = compact._safe_tail(msgs, 2)
    first = tail[0]
    is_orphan = (
        first.get("role") == "user"
        and isinstance(first.get("content"), list)
        and any(b.get("type") == "tool_result" for b in first["content"])
    )
    assert not is_orphan
    assert tail[0]["role"] == "assistant"


def test_should_compact_threshold():
    # Below the 12-message minimum: never compacts.
    short = [{"role": "user", "content": "hi"}] * 4
    assert compact.should_compact(short, 1000) is False

    # 30 msgs × 4000 chars ≈ 30k tokens; vs a small 30k-token window that
    # is well past the 72 % default trigger.
    huge = [{"role": "user", "content": "x" * 4000}] * 30
    assert compact.should_compact(huge, 30_000) is True

    # Same payload, generous window: still under the threshold.
    assert compact.should_compact(huge, 1_000_000) is False


def test_rough_tokens_monotonic():
    a = [{"role": "user", "content": "hi"}]
    b = a + [{"role": "user", "content": "x" * 1000}]
    assert compact.rough_tokens(b) > compact.rough_tokens(a)


def test_loop_shrinks_same_task_tool_bloat_before_next_model_call():
    class _Provider:
        context_window = 20_000

    msgs = [{"role": "user", "content": "go"}]
    for i in range(10):
        msgs.extend(_block_pair(i, "X" * 3_000))

    before = compact.rough_tokens(msgs)
    after = loop._maybe_shrink_context(_Provider(), msgs, render=False)

    assert after is not None
    assert after < before
    assert any(
        isinstance(block, dict)
        and block.get("type") == "tool_result"
        and str(block.get("content", "")).startswith("[old tool result elided")
        for msg in msgs
        for block in (msg.get("content") if isinstance(msg.get("content"), list) else [])
    )
