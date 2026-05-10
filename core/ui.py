"""Terminal UI for Crypt.

This module keeps the historical ``core.ui`` public API intact, but the
implementation is now a small component system instead of a pile of ad-hoc
prints. The design goal is a quiet, cinematic command cockpit: strong hierarchy,
stable layout, explicit tool states, and no decorative noise over real content.
"""
from __future__ import annotations

import math
import os
import sys
import threading
import time
from collections import deque
from typing import Iterable

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.text import Text

from .ui_kit import components as chrome
from .ui_kit import dock as dock_render
from .ui_kit import surfaces as surface_render
from .ui_kit import transcript as transcript_render
from .ui_kit import theme as ui_theme

if os.name == "nt":
    os.system("")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


THEME = ui_theme.THEME
INK = ui_theme.INK
MUTED = ui_theme.MUTED
FAINT = ui_theme.FAINT
EDGE = ui_theme.EDGE
ACCENT = ui_theme.ACCENT
ALT = ui_theme.ALT
WARN = ui_theme.WARN
ERR = ui_theme.ERR
HOT = ui_theme.HOT
GOLD = ui_theme.GOLD
RST = ui_theme.RST

DATA_DIM = ui_theme.DATA_DIM
DATA_MID = ui_theme.DATA_MID
DATA_HEAD = ui_theme.DATA_HEAD
DATA_GLITCH = ui_theme.DATA_GLITCH
ACCENT_BG = ui_theme.ACCENT_BG
WARN_BG = ui_theme.WARN_BG
ERR_BG = ui_theme.ERR_BG
INPUT_BG = ui_theme.INPUT_BG
DATA_BG = ui_theme.DATA_BG
MATRIX_DIM = ui_theme.MATRIX_DIM
MATRIX_MID = ui_theme.MATRIX_MID
MATRIX_HEAD = ui_theme.MATRIX_HEAD
MATRIX_RED = ui_theme.MATRIX_RED
MATRIX_BG = ui_theme.MATRIX_BG

_cap_lines = ui_theme.cap_lines
_ctx_color = ui_theme.ctx_color
_fmt_bytes = ui_theme.fmt_bytes
_fmt_tokens = ui_theme.fmt_tokens
_matrix_frame = ui_theme.matrix_frame
_matrix_glyph = ui_theme.matrix_glyph
_matrix_signal = ui_theme.matrix_signal
_now = ui_theme.now
_prism_signal = ui_theme.prism_signal
_short_model = ui_theme.short_model
_short_path = ui_theme.short_path
_spinner_frame = ui_theme.spinner_frame
_trim = ui_theme.trim
_wrap_text = ui_theme.wrap_text


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


console = Console(
    highlight=False,
    soft_wrap=False,
    force_terminal=True if _env_truthy("CRYPT_FORCE_TERMINAL") else None,
    legacy_windows=False,
)


_state = {
    "live": None,
    "loader_start": 0.0,
    "loader_tokens": 0,
    "todos": [],
    "tool_progress": None,
    "activity": "idle",
    "stream_kind": "",
    "stream_chars": 0,
    "pipe": None,
    "current_stream": None,
    "surface_prompt_ready": False,
    "surface_live": None,
    "surface_context": None,
    "surface_last_context": None,
    "surface_input": "",
    "surface_prompt_yolo": False,
    "surface_prompt_approval": "manual",
    "surface_reveal": None,
    "tool_lifecycle": {},
    "tool_lifecycle_order": [],
}

_TODO_DWELL_SECONDS = 0.45
_SPINNER_FRAMES = ui_theme.SPINNER_FRAMES


# ── basic formatters ──────────────────────────────────────────────────────
def _terminal_width() -> int:
    try:
        return max(40, console.size.width)
    except Exception:
        return 100


def _terminal_height() -> int:
    try:
        return max(12, console.size.height)
    except Exception:
        return 30


def _elapsed() -> int:
    start = _state["loader_start"]
    if not start:
        return 0
    return max(1, int(time.monotonic() - start))


_blank_row = chrome.blank_row
_fit_overlay = chrome.fit_overlay
_overlay_row = chrome.overlay_row
_tag = chrome.tag
_section_rule = chrome.section_rule
_panel = chrome.panel


def _matrix_rain_rows(
    width: int,
    height: int,
    frame: int | None = None,
    *,
    indent: int = 2,
) -> list[Text]:
    """Compatibility surface builder.

    The old implementation painted animated glyph rain behind content. That was
    the source of the broken screenshots. The new variant paints a sparse glass
    grid that never competes with text.
    """
    frame = _matrix_frame() if frame is None else int(frame)
    return chrome.glass_rows(width, height, frame, indent=indent)


def _packet_text(code: str, color: str) -> Text:
    return chrome.packet_text(code, color, width=_terminal_width(), now_text=_now())


def _packet(code: str, color: str) -> None:
    console.print(_packet_text(code, color))


def _print_card(kind: str, text: str, color: str, *, title: str | None = None) -> None:
    for renderable in transcript_render.card_renderables(kind, text, color, width=_terminal_width(), title=title):
        console.print(renderable)


# ── live operations dock ─────────────────────────────────────────────────
_BULLET_BY_STATE = dock_render.BULLET_BY_STATE
_blink_bullet = dock_render.blink_bullet
_elapsed_since = dock_render.elapsed_since


def _build_status() -> Text:
    return dock_render.build_status(
        activity=str(_state.get("activity") or "standby"),
        stream_kind=str(_state.get("stream_kind") or ""),
        stream_chars=int(_state.get("stream_chars") or 0),
        loader_tokens=int(_state.get("loader_tokens") or 0),
        elapsed=_elapsed() or 1,
        width=_terminal_width(),
        spinner=_spinner_frame(),
    )


def _build_tool_progress() -> Text | None:
    progress = _state.get("tool_progress")
    return dock_render.build_tool_progress(progress, width=_terminal_width())


def _build_in_flight_tools() -> RenderableType | None:
    return dock_render.build_in_flight_tools(
        list(_state.get("tool_lifecycle_order") or []),
        dict(_state.get("tool_lifecycle") or {}),
        width=_terminal_width(),
    )


def _build_todos_block() -> RenderableType | None:
    return dock_render.build_todos_block(list(_state.get("todos") or []), width=_terminal_width())


def _build_agents_block() -> RenderableType | None:
    try:
        from .agents import tasks

        items = [
            {
                "id": task.id,
                "status": task.status.value,
                "agent_type": task.agent_type,
                "name": task.name,
            }
            for task in tasks.list_tasks()
        ]
    except Exception:
        return None
    return dock_render.build_agents_block(items, width=_terminal_width())


class _LiveRenderable:
    def __rich__(self) -> RenderableType:
        parts: list[RenderableType] = []
        tools = _build_in_flight_tools()
        progress = _build_tool_progress()
        agents = _build_agents_block()
        todos = _build_todos_block()
        if tools is not None:
            parts.append(tools)
        if progress is not None:
            parts.append(progress)
        if agents is not None:
            parts.append(agents)
        if todos is not None:
            parts.append(todos)
        parts.append(_build_status())
        return _panel(Group(*parts), title="Operations Dock", border=THEME.blue)


def _refresh_live() -> None:
    live = _state.get("live")
    if live is not None:
        live.update(_LiveRenderable(), refresh=True)


def _live_start() -> None:
    if _state["live"] is not None:
        return
    live = Live(_LiveRenderable(), console=console, refresh_per_second=10, transient=True)
    live.start(refresh=True)
    _state["live"] = live


def _live_stop(render_todos: bool = False) -> None:
    live = _state.get("live")
    if live is None:
        return
    items = list(_state.get("todos") or [])
    live.stop()
    _state["live"] = None
    if render_todos:
        block = _build_todos_block()
        if block is not None:
            console.print(_panel(block, title="Mission Closed", border=THEME.green))
    if items and all(it.get("status") == "done" for it in items):
        _state["todos"] = []


def _suspend_live():
    class _Ctx:
        def __enter__(self_):
            self_.was = _state["live"] is not None
            if self_.was:
                _live_stop()
            return self_

        def __exit__(self_, *exc):
            if self_.was:
                _live_start()

    return _Ctx()


# ── tool lifecycle facade ────────────────────────────────────────────────
def tool_begin(tool_id: str, name: str, summary: str) -> None:
    if not tool_id:
        tool_call(name, summary)
        return
    width = _terminal_width()
    row = Text("  ")
    row.append("╭─", style=THEME.edge)
    row.append_text(_tag("tool", ACCENT))
    row.append(" ")
    row.append(_trim(name, 24).upper(), style=f"bold {INK}")
    if summary:
        row.append("  ")
        row.append(_trim(summary, width - len(row.plain) - 2), style=THEME.muted)
    console.print(row)

    _state.setdefault("tool_lifecycle", {})
    _state.setdefault("tool_lifecycle_order", [])
    _state["tool_lifecycle"][tool_id] = {
        "name": name,
        "summary": summary,
        "state": "queued",
        "detail": "",
        "started_at": time.monotonic(),
    }
    if tool_id not in _state["tool_lifecycle_order"]:
        _state["tool_lifecycle_order"].append(tool_id)
    _refresh_live()


def tool_set_state(tool_id: str, state: str, detail: str = "") -> None:
    if not tool_id:
        return
    entry = (_state.get("tool_lifecycle") or {}).get(tool_id)
    if entry is None:
        return
    entry["state"] = state
    if detail:
        entry["detail"] = detail
    elif state in _BULLET_BY_STATE:
        entry["detail"] = _BULLET_BY_STATE[state][2]
    if state == "running" and "running_at" not in entry:
        entry["running_at"] = time.monotonic()
    _refresh_live()


def tool_end(tool_id: str, ok: bool, output: str = "") -> None:
    if not tool_id:
        tool_result(ok, output)
        return
    lifecycle = _state.get("tool_lifecycle") or {}
    entry = lifecycle.pop(tool_id, None)
    order = _state.get("tool_lifecycle_order") or []
    if tool_id in order:
        order.remove(tool_id)

    if output:
        title = None
        if entry is not None:
            label = _trim(entry.get("name", "tool"), 24).upper()
            title = f"{label} {'OUTPUT' if ok else 'ERROR'}"
        tool_result(ok, output, title=title)
    if entry is not None:
        elapsed = _elapsed_since(entry)
        row = Text("  ")
        row.append("╰─", style=THEME.edge)
        row.append("✓ " if ok else "✕ ", style=f"bold {THEME.green if ok else ERR}")
        row.append(_trim(entry.get("name", "tool"), 24).upper(), style=f"bold {INK}")
        row.append(" ")
        row.append("COMPLETE" if ok else "FAILED", style=THEME.green if ok else ERR)
        row.append(f"  {elapsed:.1f}s", style=THEME.muted)
        console.print(row)
    _refresh_live()


def tool_lifecycle_clear() -> None:
    _state["tool_lifecycle"] = {}
    _state["tool_lifecycle_order"] = []
    _refresh_live()


# ── typewriter transcript streams ────────────────────────────────────────
class _Typewriter:
    def __init__(self, on_char) -> None:
        self._on_char = on_char
        self._q: deque[str] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)
        while self._q:
            self._on_char(self._q.popleft())

    def write(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._q.extend(text)
        self._wake.set()

    def _loop(self) -> None:
        while self._running:
            self._wake.wait(timeout=0.04)
            self._wake.clear()
            while self._q and self._running:
                with self._lock:
                    backlog = len(self._q)
                    ch = self._q.popleft() if self._q else None
                if ch is None:
                    break
                self._on_char(ch)
                delay = 0.0 if backlog > 400 else 0.0005 if backlog > 120 else 0.0015 if backlog > 30 else 0.003
                if delay:
                    time.sleep(delay)


def _stream_header(kind: str, color: str) -> None:
    width = _terminal_width()
    row = Text("  ")
    row.append("╭─", style=THEME.edge)
    row.append_text(_tag(kind, color))
    row.append(f" {_now()} ", style=THEME.muted)
    row.append("─" * max(1, width - len(row.plain) - 1), style=THEME.edge)
    console.print(row)


def _stream_footer(color: str) -> None:
    width = _terminal_width()
    row = Text("  ╰" + "─" * max(1, width - 4), style=THEME.edge)
    row.stylize(color, 2, 3)
    console.print()
    console.print(row)
    console.print()


def _emit_with_rail(rail: Text, ch: str, ink_style: str) -> None:
    if ch == "\n":
        console.print()
        console.print(rail, end="")
    else:
        console.print(ch, style=ink_style, end="", markup=False, highlight=False)


def _start_stream(kind: str, color: str, ink_style: str) -> None:
    _state["streaming_paused_live"] = _state["live"] is not None
    if _state["streaming_paused_live"]:
        _live_stop()
    _state["current_stream"] = {"kind": kind, "color": color}
    _stream_header(kind, color)
    rail = Text("  │ ", style=color)
    console.print(rail, end="")

    def on_char(ch: str) -> None:
        _emit_with_rail(rail, ch, ink_style)

    pipe = _Typewriter(on_char)
    pipe.start()
    _state["pipe"] = pipe


def _stop_stream() -> None:
    pipe: _Typewriter | None = _state.get("pipe")
    if pipe is not None:
        pipe.stop()
        _state["pipe"] = None
    stream = _state.get("current_stream") or {}
    _stream_footer(str(stream.get("color") or THEME.edge))
    _state["current_stream"] = None
    if _state.pop("streaming_paused_live", False):
        _live_start()


def thinking_start() -> None:
    _start_stream("reasoning", THEME.violet, f"italic {THEME.soft}")


def thinking_chunk(text: str) -> None:
    pipe: _Typewriter | None = _state.get("pipe")
    if pipe is not None:
        pipe.write(text)


def thinking_end() -> None:
    _stop_stream()


def assistant_start() -> None:
    _start_stream("crypt", ACCENT, INK)


def assistant_chunk(text: str) -> None:
    pipe: _Typewriter | None = _state.get("pipe")
    if pipe is not None:
        pipe.write(text)


def assistant_end() -> None:
    _stop_stream()


# ── boot, prompt, and picker surfaces ────────────────────────────────────
_BRAND = surface_render.BRAND


def _is_animated_tty() -> bool:
    if os.environ.get("CRYPT_NO_ANIMATION"):
        return False
    try:
        return bool(console.is_terminal and sys.stdout.isatty())
    except Exception:
        return False


def _can_animate_input() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(_is_animated_tty() and sys.stdin.isatty())
    except Exception:
        return False


def _tool_count() -> int:
    try:
        from tools import REGISTRY

        return len(REGISTRY.schemas())
    except Exception:
        return 0


_auth_label = surface_render.auth_label
_surface_rule = chrome.surface_rule
_surface_signal = chrome.surface_signal
_metric_row = chrome.metric_row


def _welcome_surface(
    provider: str,
    model: str,
    auth_kind: str | None,
    auth_email: str | None,
    auth_plan: str | None,
    cwd: str,
    *,
    frame: int = 0,
    reveal: int | None = None,
) -> Group:
    return surface_render.welcome_surface(
        provider,
        model,
        auth_kind,
        auth_email,
        auth_plan,
        cwd,
        width=_terminal_width(),
        height=_terminal_height() - 1,
        now_text=_now(),
        frame=frame,
        reveal=reveal,
        tool_count=_tool_count(),
    )


_prompt_palette = chrome.prompt_palette
_prompt_label = chrome.prompt_label


def _prompt_line(value: str, *, yolo: bool = False, approval: str = "manual", cursor: bool = True) -> Text:
    return chrome.prompt_line(value, width=_terminal_width(), yolo=yolo, approval=approval, cursor=cursor)


def _submitted_prompt_line(value: str, *, yolo: bool = False, approval: str = "manual") -> Text:
    return chrome.submitted_prompt_line(value, yolo=yolo, approval=approval)


class _MatrixSurfaceRenderable:
    """Compatibility class name for the animated boot surface."""

    def __rich__(self) -> RenderableType:
        ctx = _state.get("surface_context") or {}
        surface = _welcome_surface(
            str(ctx.get("provider", "")),
            str(ctx.get("model", "")),
            ctx.get("auth_kind"),
            ctx.get("auth_email"),
            ctx.get("auth_plan"),
            str(ctx.get("cwd", ".")),
            frame=_matrix_frame(),
            reveal=_state.get("surface_reveal"),
        )
        cursor = int(time.monotonic() * 2) % 2 == 0
        prompt = _prompt_line(
            str(_state.get("surface_input") or ""),
            yolo=bool(_state.get("surface_prompt_yolo")),
            approval=str(_state.get("surface_prompt_approval") or "manual"),
            cursor=cursor,
        )
        return Group(*surface.renderables, prompt)


def _prompt_pane_surface(
    value: str,
    *,
    yolo: bool = False,
    approval: str = "manual",
    frame: int | None = None,
) -> Group:
    return surface_render.prompt_pane_surface(
        value,
        width=_terminal_width(),
        height=_terminal_height(),
        yolo=yolo,
        approval=approval,
        frame=frame,
    )


class _MatrixPromptPaneRenderable:
    def __rich__(self) -> RenderableType:
        return _prompt_pane_surface(
            str(_state.get("surface_input") or ""),
            yolo=bool(_state.get("surface_prompt_yolo")),
            approval=str(_state.get("surface_prompt_approval") or "manual"),
            frame=_matrix_frame(),
        )


def _choice_surface(
    label: str,
    options: list[tuple[str, str]],
    default_idx: int,
    raw: str = "",
    error_text: str = "",
    *,
    frame: int | None = None,
) -> Group:
    return surface_render.choice_surface(
        label,
        options,
        default_idx,
        width=_terminal_width(),
        height=_terminal_height(),
        raw=raw,
        error_text=error_text,
        frame=frame,
    )


class _MatrixChoiceRenderable:
    def __init__(self, state: dict) -> None:
        self.state = state

    def __rich__(self) -> RenderableType:
        return _choice_surface(
            str(self.state.get("label", "")),
            list(self.state.get("options", [])),
            int(self.state.get("default_idx", 1)),
            str(self.state.get("raw", "")),
            str(self.state.get("error", "")),
            frame=_matrix_frame(),
        )


def _surface_live_stop() -> None:
    live = _state.get("surface_live")
    if live is not None:
        try:
            live.stop()
        except Exception:
            pass
    _state["surface_live"] = None
    if _state.get("surface_context"):
        _state["surface_last_context"] = dict(_state["surface_context"])
    _state["surface_context"] = None
    _state["surface_input"] = ""
    _state["surface_prompt_ready"] = False
    _state["surface_reveal"] = None


def _surface_live_start(context: dict) -> Live:
    _surface_live_stop()
    _state["surface_context"] = dict(context)
    _state["surface_last_context"] = dict(context)
    _state["surface_input"] = ""
    _state["surface_prompt_yolo"] = False
    _state["surface_prompt_approval"] = "manual"
    _state["surface_reveal"] = 0
    live = Live(_MatrixSurfaceRenderable(), console=console, refresh_per_second=12, transient=True)
    live.start(refresh=True)
    _state["surface_live"] = live
    return live


def _prompt_live_start(context: dict, *, yolo: bool, approval: str) -> Live:
    _surface_live_stop()
    _state["surface_context"] = dict(context)
    _state["surface_last_context"] = dict(context)
    _state["surface_input"] = ""
    _state["surface_prompt_yolo"] = yolo
    _state["surface_prompt_approval"] = approval
    _state["surface_reveal"] = None
    live = Live(_MatrixPromptPaneRenderable(), console=console, refresh_per_second=12, transient=True)
    live.start(refresh=True)
    _state["surface_live"] = live
    return live


def _viewport_clear() -> None:
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()


def _resume_surface_for_prompt(yolo: bool, approval: str) -> bool:
    if _state.get("surface_live") is not None:
        return True
    if not _can_animate_input():
        return False
    context = _state.get("surface_last_context")
    if not context:
        return False
    _prompt_live_start(dict(context), yolo=yolo, approval=approval)
    _state["surface_prompt_ready"] = True
    live = _state.get("surface_live")
    if live is not None:
        live.refresh()
    return True


def welcome(
    provider: str,
    model: str,
    auth_kind: str | None = None,
    auth_email: str | None = None,
    auth_plan: str | None = None,
    cwd: str = ".",
) -> None:
    context = {
        "provider": provider,
        "model": model,
        "auth_kind": auth_kind,
        "auth_email": auth_email,
        "auth_plan": auth_plan,
        "cwd": cwd,
    }
    _state["surface_last_context"] = dict(context)
    if not _is_animated_tty():
        console.print(f"Crypt {provider}:{model}  cwd={_short_path(cwd, 90)}")
        _state["surface_prompt_ready"] = True
        return
    if _can_animate_input():
        live = _surface_live_start(context)
        for reveal in range(1, len(_BRAND) + 1):
            _state["surface_reveal"] = reveal
            live.refresh()
            time.sleep(0.035)
        _state["surface_reveal"] = None
        _state["surface_prompt_ready"] = True
        live.refresh()
        return

    console.print(_welcome_surface(provider, model, auth_kind, auth_email, auth_plan, cwd, frame=_matrix_frame()))
    _state["surface_prompt_ready"] = True


def clear_screen() -> None:
    _surface_live_stop()
    _live_stop()
    console.clear()


def _stdin_key_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import msvcrt
    except Exception:
        return False
    try:
        return bool(msvcrt.kbhit())
    except Exception:
        return False


def _read_stdin_key() -> str:
    import msvcrt

    return msvcrt.getwch()


def _drain_buffered_lines(
    timeout_ms: int = 500,
    *,
    quiet_ms: int = 1_500,
    max_wait_ms: int = 60_000,
    max_lines: int = 20_000,
    max_chars: int = 5_000_000,
) -> list[str]:
    if os.name != "nt":
        return []
    start = time.monotonic()
    initial_deadline = start + max(0, timeout_ms) / 1000.0
    max_deadline = start + max(0, max_wait_ms) / 1000.0
    deadline = min(initial_deadline, max_deadline)
    quiet_seconds = max(0, quiet_ms) / 1000.0
    lines: list[str] = []
    current: list[str] = []
    chars_seen = 0
    last_was_cr = False

    while time.monotonic() < deadline:
        if not _stdin_key_available():
            time.sleep(0.005)
            continue

        ch = _read_stdin_key()
        deadline = min(max_deadline, time.monotonic() + quiet_seconds)

        if ch in ("\x00", "\xe0"):
            if _stdin_key_available():
                _read_stdin_key()
            continue

        if ch == "\n" and last_was_cr:
            last_was_cr = False
            continue
        last_was_cr = ch == "\r"

        if ch in ("\r", "\n"):
            lines.append("".join(current))
            current.clear()
            if len(lines) >= max_lines:
                break
        elif ch == "\b":
            if current:
                current.pop()
                chars_seen = max(0, chars_seen - 1)
        elif ch == "\t":
            current.append("    ")
            chars_seen += 4
        elif ch.isprintable():
            current.append(ch)
            chars_seen += 1

        if chars_seen >= max_chars:
            break

    if current:
        lines.append("".join(current))
    return lines


def _erase_recent_input_echo(lines: list[str], prompt_width: int = 8) -> None:
    width = _terminal_width()
    rows = 0
    for i, line in enumerate(lines):
        prefix = prompt_width if i == 0 else 0
        rows += max(1, math.ceil((prefix + len(line) + 1) / width))
    rows = max(1, min(rows, 80))
    sys.stdout.write(f"\x1b[{rows}A")
    for i in range(rows):
        sys.stdout.write("\x1b[2K")
        if i < rows - 1:
            sys.stdout.write("\x1b[1B")
    if rows > 1:
        sys.stdout.write(f"\x1b[{rows - 1}A")
    sys.stdout.flush()


def _read_surface_prompt(yolo: bool, approval: str) -> tuple[str, list[str]] | None:
    live = _state.get("surface_live")
    if live is None or not _can_animate_input():
        return None

    import msvcrt

    chars: list[str] = []
    _state["surface_prompt_yolo"] = yolo
    _state["surface_prompt_approval"] = approval
    _state["surface_input"] = ""
    live.refresh()

    try:
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    if msvcrt.kbhit():
                        msvcrt.getwch()
                    continue
                if ch in ("\r", "\n"):
                    break
                if ch in ("\x03", "\x1b"):
                    _surface_live_stop()
                    console.print()
                    return "/quit", []
                if ch == "\b":
                    if chars:
                        chars.pop()
                elif ch == "\t":
                    chars.append("    ")
                elif ch.isprintable():
                    chars.append(ch)
                _state["surface_input"] = "".join(chars)
                live.refresh()
            else:
                time.sleep(0.01)
    except KeyboardInterrupt:
        _surface_live_stop()
        console.print()
        return "/quit", []

    first = "".join(chars).strip()
    live.refresh()
    _surface_live_stop()
    if first:
        console.print(_submitted_prompt_line(first, yolo=yolo, approval=approval))
    console.print()
    extras = _drain_buffered_lines()
    return first, extras


def _read_animated_choice(label: str, options: list[tuple[str, str]], default_idx: int) -> str | None:
    if not options or not _can_animate_input():
        return None

    import msvcrt

    state = {"label": label, "options": list(options), "default_idx": default_idx, "raw": "", "error": ""}
    clear_screen()
    live = Live(_MatrixChoiceRenderable(state), console=console, refresh_per_second=12, transient=False)
    live.start(refresh=True)
    chars: list[str] = []
    try:
        while True:
            if not msvcrt.kbhit():
                time.sleep(0.01)
                continue
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                if msvcrt.kbhit():
                    msvcrt.getwch()
                continue
            if ch in ("\x03", "\x1b"):
                live.stop()
                console.print()
                return options[default_idx - 1][0]
            if ch == "\b":
                if chars:
                    chars.pop()
                state["raw"] = "".join(chars)
                state["error"] = ""
                live.refresh()
                continue
            if ch not in ("\r", "\n"):
                if ch.isprintable():
                    chars.append(ch)
                    state["raw"] = "".join(chars)
                    state["error"] = ""
                    live.refresh()
                continue

            raw = "".join(chars).strip()
            if not raw:
                live.stop()
                console.print()
                return options[default_idx - 1][0]
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                live.stop()
                console.print()
                return options[int(raw) - 1][0]
            for value, _ in options:
                if raw == value:
                    live.stop()
                    console.print()
                    return value
            state["error"] = f"choose 1-{len(options)} or type a listed value"
            chars.clear()
            state["raw"] = ""
            live.refresh()
    except KeyboardInterrupt:
        live.stop()
        console.print()
        return options[default_idx - 1][0]


def user_prompt(yolo: bool = False, approval: str = "manual") -> str:
    _resume_surface_for_prompt(yolo, approval)
    animated = _read_surface_prompt(yolo, approval)
    if animated is None:
        if _state.get("surface_live") is not None:
            _surface_live_stop()
        first = ""
        extras: list[str] = []
        if not _state.pop("surface_prompt_ready", False):
            console.print(_surface_signal(_terminal_width() - 3))
        _, fg = _prompt_palette(yolo, approval)
        prompt = Text("  ")
        prompt.append("╰─", style=THEME.edge)
        prompt.append_text(_tag(_prompt_label(yolo, approval), fg))
        prompt.append(" ")
        with _suspend_live():
            try:
                first = console.input(prompt)
            except (EOFError, KeyboardInterrupt):
                console.print()
                return "/quit"
            extras = _drain_buffered_lines()
    else:
        first, extras = animated

    is_large = extras or len(first) > 220
    if is_large:
        lines = [first, *extras]
        if animated is None:
            _erase_recent_input_echo(lines)
        full = "\n".join(lines).strip()
        total_lines = 1 + len(extras)
        non_empty_chars = sum(len(line) for line in lines)
        row = Text("  ")
        row.append("╰─", style=THEME.edge)
        row.append(f" PASTE CAPTURED  {total_lines} lines / {non_empty_chars} chars", style=f"bold {ALT}")
        console.print(row)
        return full
    return first.strip()


# ── public information surfaces ──────────────────────────────────────────
def info(text: str) -> None:
    _print_card("note", text, THEME.blue)


def error(text: str) -> None:
    _print_card("error", text, ERR)


def workspace_changed(path: str) -> None:
    _print_card("workspace", _short_path(path, 90), THEME.green)


def ask(question: str) -> bool:
    approved, _ = confirm(question)
    return approved


def confirm(question: str) -> tuple[bool, str]:
    try:
        if not sys.stdin.isatty():
            return False, "approval unavailable in non-interactive stdin"
    except Exception:
        return False, "approval unavailable in non-interactive stdin"
    console.print(_panel(Text(str(question), style=INK), title="Approval Required", border=WARN, subtitle="y/yes approves; anything else can be feedback"))
    prompt = Text("  ")
    prompt.append("╰─", style=THEME.edge)
    prompt.append_text(_tag("approve", WARN))
    prompt.append(" ")
    with _suspend_live():
        try:
            ans = console.input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return False, ""
    normalized = ans.lower()
    if normalized in {"y", "yes"}:
        return True, ""
    if normalized in {"", "n", "no"}:
        return False, ""
    return False, ans


def ask_choice(question: str, options: list[str]) -> str:
    console.print()
    rows: list[Text] = [Text(str(question), style=f"bold {INK}")]
    for i, opt in enumerate(options, 1):
        row = Text()
        row.append(f"{i:>2} ", style=THEME.muted)
        row.append(opt, style=THEME.soft)
        rows.append(row)
    console.print(_panel(Group(*rows), title="Choose", border=WARN))

    if not options:
        with _suspend_live():
            try:
                return console.input(Text("  select > ", style=ACCENT)).strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                return ""

    while True:
        with _suspend_live():
            try:
                raw = console.input(Text("  select > ", style=ACCENT)).strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                return options[0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        for opt in options:
            if raw.lower() == opt.lower():
                return opt
        error(f"choose 1-{len(options)} or type a listed option")


def splash_choice(label: str, options: list[tuple[str, str]], default_idx: int = 1) -> str:
    try:
        if not sys.stdin.isatty():
            return options[default_idx - 1][0]
    except Exception:
        return options[default_idx - 1][0]
    animated = _read_animated_choice(label, options, default_idx)
    if animated is not None:
        return animated

    console.print(_choice_surface(label, options, default_idx, frame=_matrix_frame()))
    while True:
        prompt = Text("  ")
        prompt.append("╰─", style=THEME.edge)
        prompt.append_text(_tag("select", ACCENT))
        prompt.append(f" [{default_idx}] ", style=THEME.muted)
        with _suspend_live():
            try:
                raw = console.input(prompt).strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                return options[default_idx - 1][0]
        if not raw:
            return options[default_idx - 1][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        for value, _ in options:
            if raw == value:
                return value
        error(f"choose 1-{len(options)} or type a listed value")


def read_multiline(prompt: str = "") -> str:
    if prompt:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    lines: list[str] = []
    try:
        while True:
            try:
                line = input()
            except EOFError:
                break
            if not line.strip():
                break
            lines.append(line)
    except KeyboardInterrupt:
        return ""
    return "\n".join(lines).strip()


def feedback_prompt() -> str:
    head = Text("  ")
    head.append("╭─", style=THEME.edge)
    head.append_text(_tag("feedback", WARN))
    head.append(" paste/type feedback, blank line sends", style=THEME.muted)
    console.print(head)
    with _suspend_live():
        return read_multiline("  ")


def tool_call(name: str, summary: str) -> None:
    console.print(transcript_render.tool_call_line(name, summary, width=_terminal_width()))


def tool_status(label: str, *, ok: bool | None = None) -> None:
    console.print(transcript_render.tool_status_line(label, width=_terminal_width(), ok=ok))


def tool_result(ok: bool, output: str = "", *, title: str | None = None) -> None:
    renderable = transcript_render.tool_result_panel(ok, output, width=_terminal_width(), title=title)
    if renderable is not None:
        console.print(renderable)


def tool_progress(
    name: str,
    *,
    argument_chars: int = 0,
    call_id: str = "",
    detail: str = "",
    preview: list[str] | None = None,
) -> None:
    _state["tool_progress"] = {
        "name": name,
        "argument_chars": max(0, int(argument_chars or 0)),
        "call_id": call_id,
        "detail": detail,
        "preview": list(preview or []),
    }
    _refresh_live()


def tool_progress_clear() -> None:
    if not _state.get("tool_progress"):
        return
    _state["tool_progress"] = None
    _refresh_live()


def activity(label: str) -> None:
    next_label = str(label or "waiting")
    if _state.get("activity") == next_label:
        return
    _state["activity"] = next_label
    if _state.get("tool_progress") is None:
        _refresh_live()


def stream_delta(kind: str, text: str, *, activity: str | None = None) -> None:
    kind = str(kind or "stream")
    if _state.get("stream_kind") != kind:
        _state["stream_kind"] = kind
        _state["stream_chars"] = 0
    _state["stream_chars"] = int(_state.get("stream_chars") or 0) + len(text or "")
    _state["activity"] = str(activity or f"receiving {kind} stream")
    if _state.get("tool_progress") is None:
        _refresh_live()


def stream_clear() -> None:
    _state["stream_kind"] = ""
    _state["stream_chars"] = 0
    if _state.get("tool_progress") is None:
        _refresh_live()


def todos_panel(items: list[dict]) -> None:
    _state["todos"] = list(items)
    live = _state.get("live")
    if live is None:
        return
    live.update(_LiveRenderable(), refresh=True)
    if items:
        time.sleep(_TODO_DWELL_SECONDS)


def todos_status(items: Iterable[dict]) -> str:
    items = list(items)
    if not items:
        return ""
    done = sum(1 for t in items if t.get("status") == "done")
    doing = next((t for t in items if t.get("status") == "doing"), None)
    base = f"todos {done}/{len(items)} done"
    if not doing:
        return base
    return f"{base} · doing: {doing.get('text', '')}"


def plan_panel(title: str, body: str) -> None:
    console.print()
    console.print(transcript_render.plan_panel(title, body))


def status_panel(rows: dict) -> None:
    console.print()
    console.print(transcript_render.status_panel(rows))
    console.print()


def diff_preview(text: str) -> None:
    renderable = transcript_render.diff_preview_panel(text)
    if renderable is not None:
        console.print(renderable)


def subagent_start(description: str) -> None:
    console.print(transcript_render.subagent_start_line(description, width=_terminal_width()))


def subagent_end(ok: bool, description: str) -> None:
    console.print(transcript_render.subagent_end_line(ok, description, width=_terminal_width()))
    console.print()


def footer(
    model: str,
    ctx_pct: int,
    ctx_tokens: int,
    session_tokens: int,
    cwd: str,
    yolo: bool = False,
    approval: str = "manual",
) -> None:
    last_context = dict(_state.get("surface_last_context") or {})
    if last_context:
        last_context["model"] = model
        last_context["cwd"] = cwd
        _state["surface_last_context"] = last_context

    console.print()
    console.print(transcript_render.session_footer_line(
        model=model,
        ctx_pct=ctx_pct,
        ctx_tokens=ctx_tokens,
        session_tokens=session_tokens,
        cwd=cwd,
        width=_terminal_width(),
        yolo=yolo,
        approval=approval,
    ))
    console.print()
    _state["loader_start"] = 0.0
    _state["loader_tokens"] = 0
    _state["activity"] = "standby"


class Loader:
    """Owns the animated operations dock during a model/tool turn."""

    def __init__(self, base_tokens: int = 0) -> None:
        self._base = base_tokens

    @property
    def running(self) -> bool:
        return _state["live"] is not None

    def start(self) -> None:
        _surface_live_stop()
        _state["loader_start"] = time.monotonic()
        _state["loader_tokens"] = self._base
        _state["tool_progress"] = None
        _state["activity"] = "request sent"
        _state["stream_kind"] = ""
        _state["stream_chars"] = 0
        _live_start()

    def stop(self) -> None:
        _live_stop(render_todos=bool(_state["todos"]))
        tool_lifecycle_clear()
