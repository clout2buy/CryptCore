from __future__ import annotations

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from .components import panel, section_rule, tag
from .theme import ACCENT, ALT, ERR, INK, THEME, cap_lines, ctx_color, fmt_tokens, short_model, short_path, trim, wrap_text


def card_renderables(kind: str, text: str, color: str, *, width: int, title: str | None = None) -> list[RenderableType]:
    text = str(text)
    if "\n" not in text and len(text) < width - 18:
        row = Text("  ")
        row.append("│ ", style=color)
        row.append(f"{kind.upper():<7}", style=f"bold {color}")
        row.append(" ")
        row.append(text, style=INK)
        return [row]

    body_rows = []
    for line in wrap_text(text, width - 10):
        row = Text("  ")
        row.append("│ ", style=color)
        row.append(line, style=INK if line else THEME.muted)
        body_rows.append(row)
    return [
        section_rule(title or kind, width, color),
        Group(*body_rows),
        Text("  ╰" + "─" * max(1, width - 4), style=THEME.edge),
    ]


def tool_call_line(name: str, summary: str, *, width: int) -> Text:
    row = Text("  ")
    row.append("╭─", style=THEME.edge)
    row.append_text(tag("tool", ACCENT))
    row.append(" ")
    row.append(str(name).upper(), style=f"bold {INK}")
    if summary:
        row.append("  ")
        row.append(trim(summary, width - len(row.plain) - 2), style=THEME.muted)
    return row


def tool_status_line(label: str, *, width: int, ok: bool | None = None) -> Text:
    color = THEME.muted if ok is None else THEME.green if ok else ERR
    row = Text("  ")
    row.append("│ ", style=THEME.edge)
    row.append("✓ " if ok is True else "✕ " if ok is False else "• ", style=f"bold {color}")
    row.append(trim(label, width - 8), style=color)
    return row


def tool_result_panel(ok: bool, output: str, *, width: int, title: str | None = None) -> RenderableType | None:
    text = (output or "").rstrip()
    if not text or text == "(no output)":
        return None
    lines = text.splitlines()
    visible, omitted = cap_lines(lines, 8 if ok else 12)
    color = THEME.green if ok else ERR
    panel_title = title or ("Tool Output" if ok else "Tool Error")
    rows: list[Text] = []
    for line in visible:
        row = Text()
        row.append("▏ ", style=THEME.edge)
        row.append(trim(line, width - 9), style=THEME.dim if ok else THEME.soft)
        rows.append(row)
    if omitted:
        more = Text()
        more.append("▏ ", style=THEME.edge)
        more.append(f"+{omitted} additional lines", style=THEME.muted)
        rows.append(more)
    return panel(Group(*rows), title=panel_title, border=color)


def plan_panel(title: str, body: str) -> RenderableType:
    rows: list[RenderableType] = []
    for line in body.splitlines() or [""]:
        if line.strip().startswith(("-", "*")):
            t = Text("  ")
            t.append("◆ ", style=ACCENT)
            t.append(line.strip().lstrip("-* "), style=INK)
            rows.append(t)
        else:
            rows.append(Text(line, style=THEME.soft if line.strip() else THEME.dim))
    return panel(Group(*rows), title=title or "Plan", border=THEME.amber, subtitle="review before execution")


def status_panel(rows: dict) -> RenderableType:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=THEME.muted, no_wrap=True)
    table.add_column(style=INK)
    for key, value in rows.items():
        table.add_row(str(key).upper(), str(value))
    return panel(table, title="Status", border=ALT)


def diff_preview_panel(text: str) -> RenderableType | None:
    if not text:
        return None
    lines = text.splitlines()
    visible, omitted = cap_lines(lines, 80)
    preview = "\n".join(visible)
    syntax = Syntax(preview, "diff", theme="monokai", word_wrap=False)
    subtitle = f"+{omitted} hidden lines" if omitted else ""
    return panel(syntax, title="Diff Preview", border=ALT, subtitle=subtitle)


def subagent_start_line(description: str, *, width: int) -> Text:
    row = Text("  ")
    row.append("╭─", style=THEME.edge)
    row.append_text(tag("agent lane", THEME.hot))
    row.append(" ")
    row.append(trim(description, width - 16), style=f"bold {INK}")
    return row


def subagent_end_line(ok: bool, description: str, *, width: int) -> Text:
    color = THEME.green if ok else ERR
    row = Text("  ")
    row.append("╰─", style=THEME.edge)
    row.append("✓ " if ok else "✕ ", style=f"bold {color}")
    row.append("AGENT RETURNED ", style=f"bold {color}")
    row.append(trim(description, width - 18), style=THEME.soft)
    return row


def session_footer_line(
    *,
    model: str,
    ctx_pct: int,
    ctx_tokens: int,
    session_tokens: int,
    cwd: str,
    width: int,
    yolo: bool = False,
    approval: str = "manual",
) -> Text:
    c_color = ctx_color(ctx_pct)
    bar_w = 18 if width >= 100 else 10
    filled = int(bar_w * max(0, min(100, ctx_pct)) / 100)
    if ctx_pct and filled == 0:
        filled = 1

    row = Text("  ")
    row.append("╭─", style=THEME.edge)
    row.append_text(tag("session", THEME.blue))
    row.append(" ")
    row.append(short_model(model).upper(), style=f"bold {INK}")
    row.append("  CTX ", style=THEME.muted)
    row.append("█" * filled, style=c_color)
    row.append("░" * (bar_w - filled), style=THEME.dim)
    row.append(f" {ctx_pct}% ", style=c_color)
    row.append(f"{fmt_tokens(ctx_tokens)} / {fmt_tokens(session_tokens)} TOKENS", style=THEME.muted)
    if approval in {"auto-edits", "auto-work"}:
        row.append("  AUTO", style=THEME.amber)
    elif yolo or approval == "yolo-all":
        row.append("  YOLO", style=ERR)
    if width > 78:
        row.append("  ")
        row.append(short_path(cwd, 34), style=THEME.soft)
    return row
