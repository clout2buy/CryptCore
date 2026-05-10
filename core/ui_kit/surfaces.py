from __future__ import annotations

import time

from rich.console import Group
from rich.text import Text

from .components import glass_rows, metric_row, overlay_row, prompt_line, surface_rule, surface_signal, tag
from .theme import ACCENT, INK, THEME, matrix_frame, prism_signal, short_model, short_path, trim


BRAND = (
    "   ██████╗██████╗ ██╗   ██╗██████╗ ████████╗",
    "  ██╔════╝██╔══██╗╚██╗ ██╔╝██╔══██╗╚══██╔══╝",
    "  ██║     ██████╔╝ ╚████╔╝ ██████╔╝   ██║   ",
    "  ██║     ██╔══██╗  ╚██╔╝  ██╔═══╝    ██║   ",
    "  ╚██████╗██║  ██║   ██║   ██║        ██║   ",
    "   ╚═════╝╚═╝  ╚═╝   ╚═╝   ╚═╝        ╚═╝   ",
)


def auth_label(auth_kind: str | None, auth_email: str | None, auth_plan: str | None) -> str:
    if auth_kind == "oauth":
        label = auth_email or "oauth"
        if auth_plan:
            label += f" / {auth_plan}"
        return label
    return auth_kind or "local"


def welcome_surface(
    provider: str,
    model: str,
    auth_kind: str | None,
    auth_email: str | None,
    auth_plan: str | None,
    cwd: str,
    *,
    width: int,
    height: int,
    now_text: str,
    frame: int = 0,
    reveal: int | None = None,
    tool_count: int = 0,
) -> Group:
    width = max(60, width)
    height = max(12, height)
    rows = glass_rows(width, height, frame, indent=0)
    content_x = 3 if width < 90 else 6
    content_w = max(40, width - content_x * 2)
    compact = height < 24 or width < 88
    logo_y = 2 if compact else 4

    overlays: list[tuple[int, int, Text]] = []
    top = Text("  ")
    top.append("╭─", style=THEME.edge)
    top.append(" CRYPT OPERATING CONSOLE ", style=f"bold {THEME.panel} on {ACCENT}")
    top.append(f" {now_text} ", style=THEME.muted)
    top.append("─" * max(1, content_w - len(top.plain) + 2), style=THEME.edge)
    overlays.append((1, content_x, top))

    logo_rows = len(BRAND) if reveal is None else min(len(BRAND), max(0, reveal))
    if compact:
        brand = Text("  CRYPT", style=f"bold {ACCENT}")
        brand.append("  local-first agent console", style=THEME.soft)
        overlays.append((logo_y, content_x, brand))
        info_y = logo_y + 3
    else:
        for i, line in enumerate(BRAND[:logo_rows]):
            style = f"bold {ACCENT}" if reveal is None or i < logo_rows - 1 else f"bold {THEME.white}"
            overlays.append((logo_y + i, content_x, Text(line, style=style)))
        strap = Text("  LOCAL-FIRST ENGINEERING HARNESS", style=f"bold {THEME.soft}")
        strap.append("  /  ", style=THEME.dim)
        strap.append(prism_signal(max(12, content_w // 5), frame=frame), style=THEME.blue)
        overlays.append((logo_y + len(BRAND) + 1, content_x, strap))
        info_y = logo_y + len(BRAND) + 4

    cards = [
        ("model", short_model(model), ACCENT),
        ("provider", str(provider), THEME.violet),
        ("auth", auth_label(auth_kind, auth_email, auth_plan), THEME.green),
        ("workspace", short_path(cwd, 56), THEME.soft),
        ("tools", f"{tool_count} armed", THEME.amber),
    ]
    if compact:
        for i, (label, value, color) in enumerate(cards[:4]):
            overlays.append((info_y + i, content_x, metric_row(label, value, content_w, color)))
    else:
        left = content_x
        right = content_x + min(54, content_w // 2 + 3)
        for i, (label, value, color) in enumerate(cards):
            x = left if i % 2 == 0 else right
            y = info_y + i // 2 * 2
            overlays.append((y, x, metric_row(label, value, max(32, content_w // 2 - 2), color)))

    command_y = min(height - 5, info_y + (6 if compact else 8))
    overlays.append((command_y, content_x, surface_rule("Command Deck", content_w)))
    shortcuts = Text("  │ ", style=THEME.edge)
    for i, cmd in enumerate(("/HELP", "/STATUS", "/MODEL", "/YOLO", "/COMPACT", "/QUIT")):
        if i:
            shortcuts.append("  ", style=THEME.dim)
        shortcuts.append(cmd, style=f"bold {ACCENT if i < 3 else THEME.soft}")
    overlays.append((command_y + 2, content_x, shortcuts))

    ready = Text("  ╰─", style=THEME.edge)
    ready.append(" COMMAND CHANNEL OPEN ", style=f"bold {THEME.panel} on {THEME.green}")
    ready.append(" ")
    ready.append(prism_signal(max(8, content_w // 5), frame=frame), style=THEME.blue)
    ready.append("─" * max(1, content_w - len(ready.plain) + 2), style=THEME.edge)
    overlays.append((height - 1, content_x, ready))

    for y, x, overlay in overlays:
        if 0 <= y < height:
            rows[y] = overlay_row(rows[y], overlay, x, width)
    return Group(*rows)


def prompt_pane_surface(
    value: str,
    *,
    width: int,
    height: int,
    yolo: bool = False,
    approval: str = "manual",
    frame: int | None = None,
) -> Group:
    width = max(60, width)
    height = max(6, min(9, height // 3))
    frame = matrix_frame() if frame is None else frame
    rows = glass_rows(width, height, frame, indent=0)
    content_x = 2
    content_w = max(32, width - 5)
    overlays: list[tuple[int, int, Text]] = []
    overlays.append((0, content_x, surface_rule("Command Dock", content_w)))
    hint = Text("  │ ", style=THEME.edge)
    hint.append("type a request", style=THEME.soft)
    hint.append("  /  ", style=THEME.dim)
    hint.append("Ctrl+C interrupts active work", style=THEME.muted)
    overlays.append((2, content_x, hint))
    overlays.append((height - 2, content_x, surface_signal(content_w, frame=frame)))
    overlays.append((height - 1, 0, prompt_line(value, width=width, yolo=yolo, approval=approval)))

    for y, x, overlay in overlays:
        if 0 <= y < height:
            rows[y] = overlay_row(rows[y], overlay, x, width)
    return Group(*rows)


def choice_surface(
    label: str,
    options: list[tuple[str, str]],
    default_idx: int,
    *,
    width: int,
    height: int,
    raw: str = "",
    error_text: str = "",
    frame: int | None = None,
) -> Group:
    width = max(60, width)
    height = max(12, height)
    frame = matrix_frame() if frame is None else frame
    rows = glass_rows(width, height, frame, indent=0)
    content_x = 3
    content_w = max(32, width - 7)

    overlays: list[tuple[int, int, Text]] = []
    overlays.append((1, content_x, surface_rule("Setup / Selection", content_w)))
    head = Text("  │ ", style=THEME.edge)
    head.append(str(label).upper(), style=f"bold {INK}")
    head.append("  choose one", style=THEME.muted)
    overlays.append((3, content_x, head))

    start_y = 6
    max_options = max(1, height - start_y - 4)
    for i, (_, desc) in enumerate(options[:max_options], 1):
        selected = i == default_idx
        row = Text("  ")
        row.append("│  ", style=THEME.edge)
        row.append("◆ " if selected else "◇ ", style=f"bold {ACCENT if selected else THEME.muted}")
        row.append(f"{i:>2} ", style=THEME.muted)
        row.append(trim(desc, content_w - 10), style=f"bold {INK}" if selected else THEME.soft)
        overlays.append((start_y + i - 1, content_x, row))

    prompt_y = min(height - 3, start_y + min(len(options), max_options) + 2)
    prompt = Text("  ╰─", style=THEME.edge)
    prompt.append_text(tag("select", ACCENT))
    prompt.append(f" [{default_idx}] ", style=THEME.muted)
    prompt.append(raw, style=INK)
    prompt.append("█" if int(time.monotonic() * 2) % 2 == 0 else " ", style=ACCENT)
    overlays.append((prompt_y, content_x, prompt))

    if error_text:
        err = Text("  │ ", style=THEME.edge)
        err.append("ERROR ", style=f"bold {THEME.red}")
        err.append(error_text, style=THEME.red)
        overlays.append((min(height - 2, prompt_y + 1), content_x, err))

    for y, x, overlay in overlays:
        if 0 <= y < height:
            rows[y] = overlay_row(rows[y], overlay, x, width)
    return Group(*rows)

