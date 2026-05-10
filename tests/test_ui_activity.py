from __future__ import annotations

import pytest

from core import ui


def test_status_uses_real_activity_label(monkeypatch):
    monkeypatch.setattr(ui.time, "monotonic", lambda: 105.0)
    ui._state["loader_start"] = 100.0
    ui._state["activity"] = "waiting for provider response"
    try:
        rendered = ui._build_status()
        assert "WAITING FOR PROVIDER RESPONSE" in rendered.plain
        assert "[5s]" in rendered.plain
        assert "thinking" not in rendered.plain
        assert "writing" not in rendered.plain
    finally:
        ui._state["loader_start"] = 0.0
        ui._state["activity"] = "idle"


def test_non_tty_confirm_returns_without_prompt(monkeypatch):
    monkeypatch.setattr(ui.sys.stdin, "isatty", lambda: False)

    approved, feedback = ui.confirm("run this?")

    assert approved is False
    assert "non-interactive" in feedback


def test_non_tty_splash_choice_returns_default(monkeypatch):
    monkeypatch.setattr(ui.sys.stdin, "isatty", lambda: False)

    choice = ui.splash_choice("provider", [("a", "A"), ("b", "B")], default_idx=2)

    assert choice == "b"


def test_non_tty_welcome_uses_compact_line(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(ui.console, "print", lambda value="", *args, **kwargs: seen.append(str(value)))
    monkeypatch.setattr(ui, "_is_animated_tty", lambda: False)

    ui.welcome("ollama", "gpt-oss:20b", cwd="D:\\Crypt")

    assert seen
    assert seen[-1].startswith("Crypt ollama:gpt-oss:20b")


def _reset_lifecycle():
    ui._state["tool_lifecycle"] = {}
    ui._state["tool_lifecycle_order"] = []


def test_tool_lifecycle_registers_in_flight_row():
    _reset_lifecycle()
    try:
        ui.tool_begin("call_1", "bash", "echo hi")
        assert "call_1" in ui._state["tool_lifecycle"]
        entry = ui._state["tool_lifecycle"]["call_1"]
        assert entry["state"] == "queued"
        assert entry["name"] == "bash"
        assert ui._state["tool_lifecycle_order"] == ["call_1"]
    finally:
        _reset_lifecycle()


def test_tool_lifecycle_state_transitions():
    _reset_lifecycle()
    try:
        ui.tool_begin("call_1", "bash", "echo hi")
        ui.tool_set_state("call_1", "running")
        assert ui._state["tool_lifecycle"]["call_1"]["state"] == "running"
        assert ui._state["tool_lifecycle"]["call_1"]["detail"] == "EXECUTING"

        ui.tool_set_state("call_1", "approval", "awaiting approval (rm -rf)")
        assert ui._state["tool_lifecycle"]["call_1"]["state"] == "approval"
        assert "rm -rf" in ui._state["tool_lifecycle"]["call_1"]["detail"]
    finally:
        _reset_lifecycle()


def test_tool_end_removes_from_in_flight():
    _reset_lifecycle()
    try:
        ui.tool_begin("call_1", "bash", "echo hi")
        ui.tool_end("call_1", ok=True, output="")
        assert "call_1" not in ui._state["tool_lifecycle"]
        assert "call_1" not in ui._state["tool_lifecycle_order"]
    finally:
        _reset_lifecycle()


def test_tool_lifecycle_clear_drops_leftover_rows():
    _reset_lifecycle()
    try:
        ui.tool_begin("call_1", "a", "x")
        ui.tool_begin("call_2", "b", "y")
        ui.tool_lifecycle_clear()
        assert ui._state["tool_lifecycle"] == {}
        assert ui._state["tool_lifecycle_order"] == []
    finally:
        _reset_lifecycle()


def test_in_flight_render_shows_state_and_elapsed(monkeypatch):
    _reset_lifecycle()
    try:
        # t=100: tool begins (queued)
        monkeypatch.setattr(ui.time, "monotonic", lambda: 100.0)
        ui.tool_begin("call_1", "bash", "echo hi")
        # t=104: user has been deliberating for 4s; not approved yet.
        # State is still 'queued', and the displayed elapsed is 0 because
        # running_at hasn't been stamped — approval delay is not run time.
        monkeypatch.setattr(ui.time, "monotonic", lambda: 104.0)
        ui.tool_set_state("call_1", "running")  # approved; running clock starts here
        # t=107: tool has been running for 3s.
        monkeypatch.setattr(ui.time, "monotonic", lambda: 107.0)

        group = ui._build_in_flight_tools()
        assert group is not None
        plain = "\n".join(t.plain for t in group.renderables)
        assert "EXECUTING" in plain
        assert "[3S]" in plain  # 107 - 104, NOT 107 - 100
    finally:
        _reset_lifecycle()


def test_in_flight_render_returns_none_when_empty():
    _reset_lifecycle()
    assert ui._build_in_flight_tools() is None


def test_tool_set_state_on_unknown_id_is_safe():
    _reset_lifecycle()
    # Should not raise even though the id was never registered.
    ui.tool_set_state("missing", "running")
    assert "missing" not in ui._state["tool_lifecycle"]


def test_tool_begin_without_id_falls_back_to_legacy(monkeypatch):
    """No tool_use_id → legacy single-shot tool_call, no lifecycle entry."""
    _reset_lifecycle()
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(ui, "tool_call", lambda name, summary: seen.append((name, summary)))
    ui.tool_begin("", "bash", "echo hi")
    assert seen == [("bash", "echo hi")]
    assert ui._state["tool_lifecycle"] == {}


def test_elapsed_excludes_approval_typing_time(monkeypatch):
    """Approval delay must NOT inflate the displayed run time.

    Regression for the case where 'echo hi (4.8s)' was really 'approved
    after 4.7s, ran in 0.1s' — the user reads the timer as execution speed.
    """
    _reset_lifecycle()
    try:
        # t=0: tool begin (queued)
        monkeypatch.setattr(ui.time, "monotonic", lambda: 0.0)
        ui.tool_begin("call_1", "bash", "echo hi")

        # t=5: user finally typed 'y'; tool now running.
        monkeypatch.setattr(ui.time, "monotonic", lambda: 5.0)
        ui.tool_set_state("call_1", "running")

        # t=5.1: tool finished. Footer should show 0.1s, not 5.1s.
        monkeypatch.setattr(ui.time, "monotonic", lambda: 5.1)
        entry = ui._state["tool_lifecycle"]["call_1"]
        assert ui._elapsed_since(entry) == pytest.approx(0.1, abs=0.01)
    finally:
        _reset_lifecycle()


def test_elapsed_falls_back_to_started_at_when_never_ran():
    """If the tool was denied at approval, no running_at is stamped — the
    elapsed should still be meaningful (queue/approval duration)."""
    _reset_lifecycle()
    try:
        ui.tool_begin("call_1", "bash", "echo hi")
        entry = ui._state["tool_lifecycle"]["call_1"]
        assert "running_at" not in entry
        # Should not crash, should return a small non-negative number.
        elapsed = ui._elapsed_since(entry)
        assert elapsed >= 0.0
    finally:
        _reset_lifecycle()


def test_spinner_advances_with_time(monkeypatch):
    """The status spinner must advance with the wall clock so the user
    sees motion during silent provider waits (no chunks arriving)."""
    monkeypatch.setattr(ui.time, "monotonic", lambda: 0.0)
    a = ui._spinner_frame()
    monkeypatch.setattr(ui.time, "monotonic", lambda: 0.3)
    b = ui._spinner_frame()
    # Both glyphs are valid spinner frames, and time has advanced enough
    # for the index to change (10 fps * 0.3s = 3 frames forward).
    assert a in ui._SPINNER_FRAMES
    assert b in ui._SPINNER_FRAMES
    assert a != b


def test_status_includes_spinner(monkeypatch):
    monkeypatch.setattr(ui.time, "monotonic", lambda: 105.0)
    ui._state["loader_start"] = 100.0
    ui._state["activity"] = "waiting for provider response"
    try:
        rendered = ui._build_status()
        # Spinner glyph appears as the very first non-space char.
        first_glyph = rendered.plain.lstrip()[0]
        assert first_glyph in ui._SPINNER_FRAMES
    finally:
        ui._state["loader_start"] = 0.0
        ui._state["activity"] = "idle"


def test_status_includes_matrix_signal(monkeypatch):
    monkeypatch.setattr(ui.time, "monotonic", lambda: 105.0)
    ui._state["loader_start"] = 100.0
    ui._state["activity"] = "waiting for provider response"
    try:
        rendered = ui._build_status().plain
        assert ui._matrix_signal(8) in rendered
    finally:
        ui._state["loader_start"] = 0.0
        ui._state["activity"] = "idle"


def test_matrix_rain_rows_are_sized_and_nonblank():
    rows = ui._matrix_rain_rows(32, 4, frame=6)

    assert len(rows) == 4
    assert all(len(row.plain) == 34 for row in rows)
    assert any(ch != " " for row in rows for ch in row.plain)


def test_matrix_rain_rows_can_fill_full_width_without_indent():
    rows = ui._matrix_rain_rows(32, 3, frame=6, indent=0)

    assert len(rows) == 3
    assert all(len(row.plain) == 32 for row in rows)


def test_welcome_surface_fills_viewport_and_overlays_chrome():
    surface = ui._welcome_surface(
        "openai-codex",
        "gpt-5.3-codex",
        "oauth",
        "operator@example.com",
        "Plus",
        "D:\\Crypt",
        frame=6,
    )

    rows = list(surface.renderables)
    plain = "\n".join(row.plain for row in rows)

    assert len(rows) == ui._terminal_height() - 1
    assert "CRYPT OPERATING CONSOLE" in plain
    assert "MODEL" in plain
    assert "/STATUS" in plain
    assert any(ch != " " for row in rows for ch in row.plain)


def test_matrix_surface_renderable_includes_prompt_row():
    ui._state["surface_context"] = {
        "provider": "openai-codex",
        "model": "gpt-5.3-codex",
        "auth_kind": "oauth",
        "auth_email": "operator@example.com",
        "auth_plan": "Plus",
        "cwd": "D:\\Crypt",
    }
    ui._state["surface_input"] = "hack the planet"
    try:
        rendered = ui._MatrixSurfaceRenderable().__rich__()
        rows = list(rendered.renderables)
        assert len(rows) == ui._terminal_height()
        assert "hack the planet" in rows[-1].plain
    finally:
        ui._state["surface_context"] = None
        ui._state["surface_input"] = ""


def test_prompt_pane_surface_is_compact_and_contains_input():
    surface = ui._prompt_pane_surface("keep output visible", approval="auto-work", frame=6)
    rows = list(surface.renderables)
    plain = "\n".join(row.plain for row in rows)

    assert 6 <= len(rows) <= 10
    assert "COMMAND DOCK" in plain
    assert "YOU" in rows[-1].plain
    assert "AUTO" not in rows[-1].plain
    assert "keep output visible" in rows[-1].plain


def test_surface_live_stop_keeps_last_context():
    ui._state["surface_context"] = {
        "provider": "openai-codex",
        "model": "gpt-5.3-codex",
        "cwd": "D:\\Crypt",
    }
    ui._state["surface_live"] = None
    ui._state["surface_last_context"] = None
    try:
        ui._surface_live_stop()
        assert ui._state["surface_context"] is None
        assert ui._state["surface_last_context"]["model"] == "gpt-5.3-codex"
    finally:
        ui._state["surface_context"] = None
        ui._state["surface_last_context"] = None


def test_resume_surface_for_prompt_starts_from_last_context(monkeypatch):
    class FakeLive:
        def __init__(self):
            self.refreshed = False

        def refresh(self):
            self.refreshed = True

    fake = FakeLive()
    monkeypatch.setattr(ui, "_can_animate_input", lambda: True)
    monkeypatch.setattr(ui, "_prompt_live_start", lambda context, yolo, approval: ui._state.update({
        "surface_live": fake,
        "surface_context": dict(context),
        "surface_last_context": dict(context),
        "surface_prompt_yolo": yolo,
        "surface_prompt_approval": approval,
    }) or fake)
    ui._state["surface_live"] = None
    ui._state["surface_last_context"] = {
        "provider": "openai-codex",
        "model": "gpt-5.3-codex",
        "cwd": "D:\\Crypt",
    }
    try:
        assert ui._resume_surface_for_prompt(False, "auto-work") is True
        assert fake.refreshed is True
        assert ui._state["surface_prompt_ready"] is True
        assert ui._state["surface_prompt_approval"] == "auto-work"
    finally:
        ui._state["surface_live"] = None
        ui._state["surface_context"] = None
        ui._state["surface_last_context"] = None


def test_choice_surface_fills_viewport_and_overlays_options():
    surface = ui._choice_surface(
        "provider",
        [("anthropic", "Anthropic OAuth"), ("openai-codex", "ChatGPT OAuth (Codex)")],
        2,
        raw="2",
        frame=6,
    )

    rows = list(surface.renderables)
    plain = "\n".join(row.plain for row in rows)

    assert len(rows) == ui._terminal_height()
    assert "SETUP" in plain
    assert "PROVIDER" in plain
    assert "ChatGPT OAuth" in plain
    assert "2" in plain


def test_user_prompt_uses_reserved_surface_prompt_row(monkeypatch):
    printed: list[str] = []
    monkeypatch.setattr(ui.console, "print", lambda obj=None, *args, **kwargs: printed.append(getattr(obj, "plain", "")))
    monkeypatch.setattr(ui.console, "input", lambda prompt: "scan target")
    monkeypatch.setattr(ui, "_drain_buffered_lines", lambda timeout_ms=80: [])
    ui._state["surface_prompt_ready"] = True
    try:
        assert ui.user_prompt() == "scan target"
        assert not any("╶" in item for item in printed)
    finally:
        ui._state["surface_prompt_ready"] = False


def test_drain_buffered_lines_waits_for_delayed_paste_tail(monkeypatch):
    now = 0.0
    chars = list("tail one\r\ncontinued")
    release_at = 0.03

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def key_available() -> bool:
        return bool(chars) and now >= release_at

    def read_key() -> str:
        return chars.pop(0)

    monkeypatch.setattr(ui.os, "name", "nt", raising=False)
    monkeypatch.setattr(ui.time, "monotonic", monotonic)
    monkeypatch.setattr(ui.time, "sleep", sleep)
    monkeypatch.setattr(ui, "_stdin_key_available", key_available)
    monkeypatch.setattr(ui, "_read_stdin_key", read_key)

    drained = ui._drain_buffered_lines(timeout_ms=80, quiet_ms=50, max_wait_ms=500)

    assert drained == ["tail one", "continued"]
    assert chars == []


def test_drain_buffered_lines_extends_until_paste_is_quiet(monkeypatch):
    now = 0.0
    chars = list("one\r\ntwo\r\nthree")
    next_release = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def key_available() -> bool:
        return bool(chars) and now >= next_release

    def read_key() -> str:
        nonlocal next_release
        ch = chars.pop(0)
        next_release = now + 0.03
        return ch

    monkeypatch.setattr(ui.os, "name", "nt", raising=False)
    monkeypatch.setattr(ui.time, "monotonic", monotonic)
    monkeypatch.setattr(ui.time, "sleep", sleep)
    monkeypatch.setattr(ui, "_stdin_key_available", key_available)
    monkeypatch.setattr(ui, "_read_stdin_key", read_key)

    drained = ui._drain_buffered_lines(timeout_ms=20, quiet_ms=60, max_wait_ms=1000)

    assert drained == ["one", "two", "three"]
    assert chars == []


def test_drain_buffered_lines_default_window_handles_slow_large_paste(monkeypatch):
    now = 0.0
    chars = list(("line\n" * 120).rstrip("\n"))
    next_release = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def key_available() -> bool:
        return bool(chars) and now >= next_release

    def read_key() -> str:
        nonlocal next_release
        ch = chars.pop(0)
        next_release = now + 0.01
        return ch

    monkeypatch.setattr(ui.os, "name", "nt", raising=False)
    monkeypatch.setattr(ui.time, "monotonic", monotonic)
    monkeypatch.setattr(ui.time, "sleep", sleep)
    monkeypatch.setattr(ui, "_stdin_key_available", key_available)
    monkeypatch.setattr(ui, "_read_stdin_key", read_key)

    drained = ui._drain_buffered_lines()

    assert len(drained) == 120
    assert chars == []


def test_drain_buffered_lines_default_window_handles_very_large_slow_paste(monkeypatch):
    now = 0.0
    chars = list(("x\n" * 2000).rstrip("\n"))
    next_release = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def key_available() -> bool:
        return bool(chars) and now >= next_release

    def read_key() -> str:
        nonlocal next_release
        ch = chars.pop(0)
        next_release = now + 0.01
        return ch

    monkeypatch.setattr(ui.os, "name", "nt", raising=False)
    monkeypatch.setattr(ui.time, "monotonic", monotonic)
    monkeypatch.setattr(ui.time, "sleep", sleep)
    monkeypatch.setattr(ui, "_stdin_key_available", key_available)
    monkeypatch.setattr(ui, "_read_stdin_key", read_key)

    drained = ui._drain_buffered_lines()

    assert len(drained) == 2000
    assert chars == []


def test_activity_does_not_refresh_when_label_is_unchanged(monkeypatch):
    class Live:
        def __init__(self):
            self.calls = 0

        def update(self, *args, **kwargs):
            self.calls += 1

    live = Live()
    ui._state["live"] = live
    ui._state["activity"] = "planning file tool call"
    try:
        ui.activity("planning file tool call")
        assert live.calls == 0
        ui.activity("receiving tool args: write_file")
        assert live.calls == 1
    finally:
        ui._state["live"] = None
        ui._state["activity"] = "idle"


def test_status_shows_abort_hint_after_long_wait(monkeypatch):
    """After 15s of no chunks, the status surfaces ctrl+c / /model hint."""
    monkeypatch.setattr(ui.time, "monotonic", lambda: 120.0)
    ui._state["loader_start"] = 100.0  # 20s elapsed
    ui._state["activity"] = "waiting for provider response"
    ui._state["stream_chars"] = 0  # nothing received yet
    try:
        rendered = ui._build_status().plain
        assert "[CTRL+C] ABORT" in rendered
        assert "[/MODEL] SWITCH" in rendered
    finally:
        ui._state["loader_start"] = 0.0
        ui._state["activity"] = "idle"


def test_status_hides_abort_hint_once_chunks_arrive(monkeypatch):
    """Once any chunk has been received, the wait hint goes away — we're
    no longer 'stuck', the model is producing output."""
    monkeypatch.setattr(ui.time, "monotonic", lambda: 120.0)
    ui._state["loader_start"] = 100.0
    ui._state["activity"] = "receiving text stream"
    ui._state["stream_chars"] = 50
    try:
        rendered = ui._build_status().plain
        assert "Ctrl+C to abort" not in rendered
    finally:
        ui._state["loader_start"] = 0.0
        ui._state["activity"] = "idle"
        ui._state["stream_chars"] = 0


def test_status_hides_abort_hint_when_response_complete(monkeypatch):
    monkeypatch.setattr(ui.time, "monotonic", lambda: 120.0)
    ui._state["loader_start"] = 100.0
    ui._state["activity"] = "response complete"
    ui._state["stream_chars"] = 0
    try:
        rendered = ui._build_status().plain
        assert "[CTRL+C] ABORT" not in rendered
        assert "RESPONSE COMPLETE" in rendered
    finally:
        ui._state["loader_start"] = 0.0
        ui._state["activity"] = "idle"
        ui._state["stream_chars"] = 0


def test_choice_surface_clears_background_after_option_text():
    surface = ui._choice_surface(
        "model",
        [("gpt-5.5", "gpt-5.5"), ("spark", "gpt-5.3-codex-spark")],
        1,
        frame=6,
    )

    plain_rows = [row.plain for row in surface.renderables]
    option = next(row for row in plain_rows if "gpt-5.5" in row)
    suffix = option.split("gpt-5.5", 1)[1][:3]
    assert "·" not in suffix


def test_artifact_hidden_thinking_surfaces_collapsed_liveness(monkeypatch, workspace):
    from core import loop, runtime
    from core.api import ThinkingDelta, TurnEnd

    class Provider:
        name = "fake"
        model = "fake-model"
        is_oauth = False

        def stream_turn(self, messages, tools, system):
            yield ThinkingDelta("private planning")
            yield TurnEnd(
                stop_reason="end_turn",
                message={"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            )

    runtime.configure(Provider(), str(workspace), session=None)
    runtime.set_show_thinking(False)
    seen: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        loop.ui,
        "stream_delta",
        lambda kind, text, activity=None: seen.append((kind, text, activity or "")),
    )
    monkeypatch.setattr(loop.ui, "stream_clear", lambda: None)
    monkeypatch.setattr(loop.ui, "tool_progress_clear", lambda: None)

    loop._stream_one_turn(
        Provider(),
        messages=[{"role": "user", "content": "make an interactive html"}],
        tools=[],
        loader=loop._SilentLoader(),
        render=True,
    )

    assert seen == [("thinking", "private planning", "planning file tool call")]


def test_stream_delta_can_preserve_activity_label():
    ui._state["stream_kind"] = ""
    ui._state["stream_chars"] = 0
    ui._state["activity"] = "idle"
    try:
        ui.stream_delta("thinking", "abc", activity="planning file tool call")

        assert ui._state["stream_kind"] == "thinking"
        assert ui._state["stream_chars"] == 3
        assert ui._state["activity"] == "planning file tool call"
    finally:
        ui._state["stream_kind"] = ""
        ui._state["stream_chars"] = 0
        ui._state["activity"] = "idle"


def test_tool_progress_renders_detail():
    try:
        ui.tool_progress(
            "write_file",
            argument_chars=2048,
            call_id="toolu_123456789",
            detail="demo.html - 80 line(s), 4,200 chars",
            preview=["<canvas id=\"stage\">", "requestAnimationFrame(tick)"],
        )

        rendered = ui._build_tool_progress()

        assert rendered is not None
        plain = rendered.plain
        assert "ARGUMENT STREAM" in plain
        assert "WRITE_FILE" in plain
        assert "demo.html" in plain
        assert "80 line(s)" in plain
        assert "requestAnimationFrame" in plain
    finally:
        ui.tool_progress_clear()
