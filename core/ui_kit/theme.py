from __future__ import annotations

import textwrap
import time
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Theme:
    ink: str = "rgb(232,241,255)"
    soft: str = "rgb(177,194,217)"
    muted: str = "rgb(104,126,154)"
    dim: str = "rgb(56,73,99)"
    edge: str = "rgb(28,37,55)"
    panel: str = "rgb(9,14,24)"
    panel_hi: str = "rgb(13,22,36)"
    cyan: str = "rgb(77,229,255)"
    blue: str = "rgb(99,157,255)"
    violet: str = "rgb(191,133,255)"
    amber: str = "rgb(255,191,71)"
    green: str = "rgb(75,230,165)"
    red: str = "rgb(255,86,122)"
    hot: str = "rgb(255,111,206)"
    white: str = "rgb(255,255,255)"


THEME = Theme()

INK = THEME.ink
MUTED = THEME.muted
FAINT = THEME.dim
EDGE = THEME.edge
ACCENT = THEME.cyan
ALT = THEME.violet
WARN = THEME.amber
ERR = THEME.red
HOT = THEME.hot
GOLD = WARN
RST = ""

DATA_DIM = THEME.dim
DATA_MID = THEME.blue
DATA_HEAD = THEME.cyan
DATA_GLITCH = THEME.white
ACCENT_BG = f"on {THEME.edge}"
WARN_BG = f"on {THEME.edge}"
ERR_BG = f"on {THEME.edge}"
INPUT_BG = f"on {THEME.panel_hi}"
DATA_BG = f"on {THEME.panel}"
MATRIX_DIM = DATA_DIM
MATRIX_MID = DATA_MID
MATRIX_HEAD = DATA_HEAD
MATRIX_RED = ERR
MATRIX_BG = DATA_BG

SPINNER_FRAMES = "◐◓◑◒"
SIGNAL_GLYPHS = "▰▱◆◇"


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def short_path(path: str, limit: int = 44) -> str:
    s = str(path)
    if len(s) <= limit:
        return s
    keep = max(8, limit - 3)
    return "..." + s[-keep:]


def short_model(model: str) -> str:
    m = str(model).removeprefix("claude-")
    parts = m.split("-")
    if parts and len(parts[-1]) >= 8 and parts[-1].isdigit():
        parts.pop()
    if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
        parts[-2:] = [f"{parts[-2]}.{parts[-1]}"]
    return " ".join(parts)


def trim(text: str, limit: int) -> str:
    clean = " ".join(str(text).split())
    if limit <= 0:
        return ""
    return clean if len(clean) <= limit else clean[: max(1, limit - 1)] + "…"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1_000:.0f}k"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return f"{n}"


def fmt_bytes(n: int) -> str:
    n = max(0, int(n or 0))
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    if n >= 10_000:
        return f"{n / 1_000:.0f} KB"
    if n >= 1_000:
        return f"{n / 1_000:.1f} KB"
    return f"{n} B"


def ctx_color(pct: int) -> str:
    if pct < 50:
        return THEME.green
    if pct < 80:
        return WARN
    return ERR


def spinner_frame() -> str:
    return SPINNER_FRAMES[int(time.monotonic() * 10) % len(SPINNER_FRAMES)]


def prism_signal(width: int = 10, *, frame: int | None = None) -> str:
    frame = int(time.monotonic() * 8) if frame is None else int(frame)
    width = max(1, int(width))
    return "".join(SIGNAL_GLYPHS[(frame + i * 2 + i // 3) % len(SIGNAL_GLYPHS)] for i in range(width))


def matrix_signal(width: int = 10) -> str:
    return prism_signal(width)


def matrix_glyph(seed: int) -> str:
    return SIGNAL_GLYPHS[abs(seed) % len(SIGNAL_GLYPHS)]


def matrix_frame() -> int:
    return int(time.monotonic() * 8)


def cap_lines(lines: list[str], cap: int) -> tuple[list[str], int]:
    visible = lines[:cap]
    return visible, max(0, len(lines) - len(visible))


def wrap_text(text: str, width: int) -> list[str]:
    out: list[str] = []
    for raw in str(text).splitlines() or [""]:
        if not raw:
            out.append("")
            continue
        out.extend(textwrap.wrap(raw, width=max(12, width), replace_whitespace=False) or [""])
    return out

