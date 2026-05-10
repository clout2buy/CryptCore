from __future__ import annotations

import time

from rich.console import Group, RenderableType
from rich.text import Text

from .theme import ACCENT, ALT, ERR, INK, THEME, fmt_bytes, fmt_tokens, prism_signal, trim


BULLET_BY_STATE = {
    "queued": ("◇", THEME.muted, "QUEUED"),
    "approval": ("◆", THEME.amber, "AWAITING APPROVAL"),
    "running": ("◆", ACCENT, "EXECUTING"),
    "ok": ("✓", THEME.green, "COMPLETE"),
    "err": ("✕", ERR, "FAILED"),
}


def blink_bullet(bullet: str, state: str) -> str:
    if state in {"approval", "running"} and int(time.monotonic() * 3) % 2 == 0:
        return "◇"
    return bullet


def elapsed_since(entry: dict) -> float:
    ref = entry.get("running_at") or entry.get("started_at")
    if not ref:
        return 0.0
    return max(0.0, time.monotonic() - ref)


def build_status(
    *,
    activity: str,
    stream_kind: str,
    stream_chars: int,
    loader_tokens: int,
    elapsed: int,
    width: int,
    spinner: str,
) -> Text:
    t = Text("  ")
    t.append(spinner, style=f"bold {ACCENT}")
    t.append(" ")
    t.append(prism_signal(8), style=THEME.blue)
    t.append("  ")
    t.append(trim(activity.upper(), max(18, width - 44)), style=f"bold {INK}")
    t.append(f"  [{elapsed}s]", style=THEME.muted)
    if stream_chars:
        t.append(f"  {fmt_bytes(stream_chars)}", style=THEME.muted)
        if stream_kind:
            t.append(f" {stream_kind.upper()}", style=THEME.muted)
    if loader_tokens:
        t.append(f"  {fmt_tokens(loader_tokens)} TOKENS", style=THEME.muted)
    if stream_chars == 0 and elapsed >= 15 and "complete" not in activity.lower():
        t.append("  [CTRL+C] ABORT  [/MODEL] SWITCH", style=THEME.amber)
    return t


def build_tool_progress(progress: dict | None, *, width: int) -> Text | None:
    if not progress:
        return None
    name = trim(progress.get("name") or "tool", 28).upper()
    chars = int(progress.get("argument_chars") or 0)
    call_id = str(progress.get("call_id") or "")
    detail = str(progress.get("detail") or "")
    preview = list(progress.get("preview") or [])

    t = Text("  ")
    head = Text()
    head.append("╞ ", style=THEME.edge)
    head.append("ARGUMENT STREAM", style=f"bold {ALT}")
    head.append(f"  {name}", style=f"bold {INK}")
    if chars:
        head.append(f"  {fmt_bytes(chars)}", style=THEME.muted)
    if call_id:
        head.append(f"  {call_id[:12]}", style=THEME.dim)
    t.append_text(head)

    if detail:
        row = Text("\n  ")
        row.append("│   ", style=THEME.edge)
        row.append(trim(detail, width - 8), style=THEME.soft)
        t.append_text(row)

    for line in preview[-3:]:
        row = Text("\n  ")
        row.append("│   ", style=THEME.edge)
        row.append("▏ ", style=THEME.dim)
        row.append(trim(str(line), width - 10), style=THEME.dim)
        t.append_text(row)
    return t


def build_in_flight_tools(order: list[str], lifecycle: dict, *, width: int) -> RenderableType | None:
    rows: list[Text] = []
    for tid in order:
        entry = lifecycle.get(tid)
        if not entry:
            continue
        state = entry.get("state", "queued")
        bullet, color, default_detail = BULLET_BY_STATE.get(state, BULLET_BY_STATE["queued"])
        bullet = blink_bullet(bullet, state)
        name = trim(entry.get("name", "tool"), 22).upper()
        detail = entry.get("detail") or default_detail
        elapsed = int(elapsed_since(entry))
        row = Text("  ")
        row.append("╞ ", style=THEME.edge)
        row.append(bullet + " ", style=f"bold {color}")
        row.append(f"{name:<22}", style=f"bold {INK}")
        row.append(trim(str(detail).upper(), max(12, width - 42)), style=THEME.soft)
        if elapsed >= 1:
            row.append(f"  [{elapsed}S]", style=THEME.muted)
        rows.append(row)
    return Group(*rows) if rows else None


def build_agents_block(items: list[dict], *, width: int) -> RenderableType | None:
    rows: list[Text] = []
    active = [
        item for item in items
        if item.get("status") in {"queued", "running", "cancel_requested"}
    ]
    if not active:
        return None
    head = Text("  ")
    head.append("╞ ", style=THEME.edge)
    head.append("AGENT LANES", style=f"bold {THEME.hot}")
    head.append(f"  {len(active)} ACTIVE", style=THEME.muted)
    rows.append(head)
    for item in active[:4]:
        status = str(item.get("status") or "running")
        marker, color = {
            "queued": ("◇", THEME.muted),
            "running": ("◆", ACCENT),
            "cancel_requested": ("◇", THEME.amber),
        }.get(status, ("◇", THEME.muted))
        row = Text("  ")
        row.append("│   ", style=THEME.edge)
        row.append(marker + " ", style=f"bold {color}")
        row.append(trim(str(item.get("id") or "agent"), 12), style=f"bold {INK}")
        row.append(" ")
        row.append(trim(str(item.get("agent_type") or "agent"), 14).upper(), style=THEME.soft)
        row.append(" ")
        row.append(trim(str(item.get("name") or ""), max(8, width - 42)), style=THEME.muted)
        rows.append(row)
    if len(active) > 4:
        row = Text("  │   ", style=THEME.edge)
        row.append(f"+{len(active) - 4} more agent task(s)", style=THEME.dim)
        rows.append(row)
    return Group(*rows)


def build_todos_block(items: list[dict], *, width: int) -> RenderableType | None:
    if not items:
        return None
    done = sum(1 for it in items if it.get("status") == "done")
    active = next((it for it in items if it.get("status") == "doing"), None)
    rows: list[Text] = []

    head = Text("  ")
    head.append("╞ ", style=THEME.edge)
    head.append("MISSION BOARD", style=f"bold {THEME.green if done == len(items) else THEME.amber}")
    head.append(f"  {done}/{len(items)}", style=THEME.muted)
    if active:
        head.append("  ")
        head.append(trim(active.get("text", "working"), width - 34).upper(), style=f"bold {INK}")
    rows.append(head)

    for it in items[:5]:
        status = it.get("status", "pending")
        text = trim(it.get("text", ""), width - 14)
        marker, color = {
            "done": ("✓", THEME.green),
            "doing": ("◆", ACCENT),
            "pending": ("◇", THEME.muted),
        }.get(status, ("◇", THEME.muted))
        row = Text("  ")
        row.append("│   ", style=THEME.edge)
        row.append(marker + " ", style=f"bold {color}")
        row.append(text, style=(f"strike {THEME.dim}" if status == "done" else THEME.soft))
        rows.append(row)
    if len(items) > 5:
        row = Text("  │   ", style=THEME.edge)
        row.append(f"+{len(items) - 5} more", style=THEME.dim)
        rows.append(row)
    return Group(*rows)
