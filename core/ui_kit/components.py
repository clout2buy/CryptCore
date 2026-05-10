from __future__ import annotations

from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text

from .theme import ACCENT, DATA_BG, INK, THEME, prism_signal, trim


def blank_row(width: int, style: str = DATA_BG) -> Text:
    return Text(" " * max(0, width), style=style)


def fit_overlay(text: Text, width: int) -> Text:
    if len(text.plain) <= width:
        return text
    return Text(trim(text.plain, width), style=text.style or INK)


def overlay_row(base: Text, overlay: Text, col: int, width: int) -> Text:
    col = max(0, min(col, max(0, width - 1)))
    left = base.plain[:col]
    row = Text(left, style=base.style)
    row.append_text(fit_overlay(overlay, max(1, width - col)))
    if len(row.plain) < width:
        fill = max(0, width - len(row.plain) - 1)
        if fill:
            row.append(" " * fill, style=base.style)
        if base.plain:
            row.append(base.plain[-1], style=base.style)
    return row


def glass_rows(width: int, height: int, frame: int, *, indent: int = 2) -> list[Text]:
    width = max(24, int(width))
    height = max(1, int(height))
    indent = max(0, int(indent))
    rows: list[Text] = []
    for row in range(height):
        t = Text(" " * indent)
        for col in range(width):
            if row in {0, height - 1} and col % 4 == frame % 4:
                t.append("─", style=THEME.edge)
            elif col in {0, width - 1}:
                t.append("│", style=THEME.edge)
            elif (row * 17 + col * 7 + frame) % 251 == 0:
                t.append("·", style=THEME.dim)
            else:
                t.append(" ")
        rows.append(t)
    return rows


def tag(label: str, style: str, *, inverse: bool = True) -> Text:
    t = Text()
    label = f" {label.upper()} "
    if inverse:
        t.append(label, style=f"bold {THEME.panel} on {style}")
    else:
        t.append(label, style=f"bold {style}")
    return t


def section_rule(label: str, width: int, color: str = ACCENT) -> Text:
    label_text = f" {label.upper()} "
    left = Text("  ╭─", style=THEME.edge)
    left.append(label_text, style=f"bold {color}")
    fill = max(1, width - len(left.plain) - 1)
    left.append("─" * fill, style=THEME.edge)
    return left


def packet_text(code: str, color: str, *, width: int, now_text: str) -> Text:
    t = Text("  ")
    t.append("╭─", style=THEME.edge)
    t.append_text(tag(code, color))
    t.append(f" {now_text} ", style=THEME.muted)
    t.append("─" * max(1, width - len(t.plain) - 1), style=THEME.edge)
    return t


def panel(renderable: RenderableType, *, title: str, border: str = THEME.edge, subtitle: str = "") -> Panel:
    return Panel(
        renderable,
        title=f"[bold {border}]{title.upper()}[/]",
        subtitle=f"[{THEME.muted}]{subtitle}[/]" if subtitle else "",
        border_style=border,
        padding=(0, 1),
    )


def surface_rule(label: str, width: int) -> Text:
    t = Text("  ")
    t.append("╭─", style=THEME.edge)
    t.append(f" {label.upper()} ", style=f"bold {ACCENT}")
    t.append("─" * max(1, width - len(t.plain) - 1), style=THEME.edge)
    return t


def surface_signal(width: int, *, frame: int | None = None) -> Text:
    t = Text("  ")
    t.append("╞ ", style=THEME.edge)
    t.append(prism_signal(max(8, min(28, width // 4)), frame=frame), style=THEME.blue)
    t.append("  READY", style=f"bold {THEME.green}")
    t.append("  ")
    t.append("─" * max(1, width - len(t.plain) - 1), style=THEME.edge)
    return t


def metric_row(label: str, value: str, width: int, color: str = ACCENT) -> Text:
    t = Text("  ")
    t.append("│ ", style=THEME.edge)
    t.append(f"{label.upper():<10}", style=THEME.muted)
    t.append(" ")
    t.append(trim(value, width - 17), style=f"bold {color}")
    return t


def prompt_palette(yolo: bool = False, approval: str = "manual") -> tuple[str, str]:
    if yolo or approval == "yolo-all":
        return f"on {THEME.edge}", THEME.red
    if approval in {"auto-edits", "auto-work"}:
        return f"on {THEME.edge}", THEME.amber
    return f"on {THEME.panel_hi}", THEME.cyan


def prompt_label(yolo: bool, approval: str) -> str:
    return "YOU"


def prompt_line(
    value: str,
    *,
    width: int,
    yolo: bool = False,
    approval: str = "manual",
    cursor: bool = True,
) -> Text:
    _, fg = prompt_palette(yolo, approval)
    label = prompt_label(yolo, approval)
    t = Text(" ")
    t.append("╭─", style=THEME.edge)
    t.append_text(tag(label, fg))
    t.append(" ")
    max_value = max(1, width - len(t.plain) - 3)
    shown = str(value)
    if len(shown) > max_value:
        shown = "…" + shown[-max(1, max_value - 1):]
    t.append(shown, style=INK)
    t.append("█" if cursor else " ", style=fg)
    if len(t.plain) < width:
        t.append(" " * (width - len(t.plain)), style=f"on {THEME.panel}")
    return t


def submitted_prompt_line(value: str, *, yolo: bool = False, approval: str = "manual") -> Text:
    _, fg = prompt_palette(yolo, approval)
    label = prompt_label(yolo, approval)
    t = Text("  ")
    t.append("╭─", style=THEME.edge)
    t.append_text(tag(label, fg))
    t.append(" ")
    t.append(str(value), style=INK)
    return t
