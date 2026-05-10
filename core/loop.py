"""Agent loop: stream, dispatch tools, repeat."""
from __future__ import annotations

import contextvars
import json
import os
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable

from . import (
    artifacts,
    background,
    compact,
    doctor,
    evidence,
    file_state,
    final_claims,
    memory,
    prompt as prompt_builder,
    runtime,
    tool_recovery,
)
from .agents import orchestrator
from .agents import registry as agent_registry
from . import verifiers
from . import session as sessions
from . import tracing, ui
from .api import Provider, TextDelta, ThinkingDelta, ToolUseProgress, ToolUseReady, TurnEnd
from tools import REGISTRY, dispatch

EventSink = Callable[[dict], None]


def _emit_event(event_sink: EventSink | None, payload: dict) -> None:
    if event_sink is None:
        return
    try:
        event_sink(payload)
    except Exception as exc:
        tracing.emit(
            "event_sink_error",
            error=f"{type(exc).__name__}: {exc}",
            event=payload.get("event", ""),
        )


def _event_text_preview(value, *, limit: int = 4000) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except TypeError:
            text = str(value)
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}\n... truncated {len(text) - limit:,} chars"


class ReasoningStallError(RuntimeError):
    """Raised when hidden reasoning makes no visible progress for too long."""


_BASE_SYSTEM = """You are Crypt, a local-first software engineering agent.

Work like a careful engineer:
- inspect before editing
- prefer edit_file for existing files; write_file is for new files
- use open_file to open generated local files
- keep changes small, idiomatic, and easy to review
- run focused tests or checks after edits when practical
- when using todos, keep narration minimal and let the live todo panel show progress
- execute large requests one verified phase at a time unless the user explicitly says to do all phases now
- when asked to create/build/write an artifact or file, use write_file/edit_file instead of pasting the full artifact in chat
- if a tool result says schema validation failed, fix the arguments once and then change approach if it fails again
- keep execution narration short; avoid long audits unless asked
- never claim a phase is complete without naming the verification that passed
- if an edit tool fails in a risky state, stop and explain the recovery instead of improvising shell hacks
- if a tool is denied or fails with a permission error, adapt to the user's feedback instead of retrying stale calls
- open_file only opens a file for the user; it does not let you inspect image/video contents
- be concise and report blockers directly
""".strip()


@dataclass
class RunResult:
    messages: list[dict]
    final_text: str
    current_tokens: int = 0
    session_tokens: int = 0


def _build_system_prompt() -> str:
    guidance = REGISTRY.prompts()
    if not guidance:
        return _BASE_SYSTEM
    return f"{_BASE_SYSTEM}\n\n# Tool guidance\n\n{guidance}"


def run_prompt(
    provider: Provider,
    user_text: str,
    *,
    cwd: str = ".",
    session_obj=None,
    max_turns: int = 50,
    approval_mode: str = runtime.APPROVAL_ALL,
    show_thinking: bool = False,
    render: bool = False,
    subagent_provider_factory=None,
    event_sink: EventSink | None = None,
) -> RunResult:
    """Run one prompt to completion without the interactive input loop.

    This is the production entry point for benchmarks, CI smoke checks, and
    scripted integrations. It uses the same provider/tool loop as the terminal
    UI, but approvals are governed by ``approval_mode`` instead of prompts.
    """
    previous_mode = runtime.approval_mode()
    previous_thinking_mode = runtime.thinking_mode()
    evidence.clear()
    messages: list[dict] = session_obj.load_messages() if session_obj else []

    def run_subagent(prompt, context=None, **kwargs):
        sub_provider = provider
        if subagent_provider_factory is not None:
            sub_provider = subagent_provider_factory(kwargs.get("agent_type", "explorer")) or provider
        return _run_subagent(sub_provider, prompt, context, **kwargs)

    runtime.configure(
        provider,
        cwd,
        run_subagent,
        session=session_obj,
    )
    if show_thinking != runtime.show_thinking():
        runtime.set_show_thinking(show_thinking)
    runtime.set_approval_mode(approval_mode)
    REGISTRY.before_prompt()
    user_msg = {"role": "user", "content": user_text}
    messages.append(user_msg)
    if runtime.session():
        runtime.session().record_message(user_msg)
    tracing.emit("run_start", mode="non_interactive", prompt=user_text, max_turns=max_turns)
    try:
        current_tokens, session_tokens = _run_until_done(
            provider,
            messages,
            0,
            compact.rough_tokens(messages),
            max_turns=max_turns,
            render=render,
            event_sink=event_sink,
        )
        final_text = _extract_text(messages[-1]) if messages else ""
        tracing.emit(
            "run_stop",
            mode="non_interactive",
            message_count=len(messages),
            current_tokens=current_tokens,
            session_tokens=session_tokens,
            final_text=final_text[:1000],
        )
        return RunResult(
            messages=messages,
            final_text=final_text,
            current_tokens=current_tokens,
            session_tokens=session_tokens,
        )
    except Exception as exc:
        tracing.emit("run_error", mode="non_interactive", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        runtime.set_approval_mode(previous_mode)
        runtime.set_thinking_mode(previous_thinking_mode)


def run(
    provider: Provider,
    show_thinking: bool = False,
    cwd: str = ".",
    model_switcher=None,
    session_obj=None,
) -> str | None:
    """Run the TAOR loop. Returns 'login'/'logout' if the user asked, or None on quit."""
    messages: list[dict] = session_obj.load_messages() if session_obj else []
    current_tokens = 0
    session_tokens = compact.rough_tokens(messages) if messages else 0
    runtime.configure(
        provider,
        cwd,
        lambda prompt, context=None, **kwargs: _run_subagent(provider, prompt, context, **kwargs),
        session=session_obj,
    )
    runtime.set_show_thinking(show_thinking)
    tracing.emit("session_start", mode="interactive", resumed=bool(messages), message_count=len(messages))
    if session_obj and messages:
        _restore_tool_state(messages)
        ui.info(f"resumed session {session_obj.id} with {len(messages)} message(s)")

    while True:
        REGISTRY.before_prompt()
        user_text = ui.user_prompt(
            yolo=runtime.yolo(),
            approval=runtime.approval_label(),
        )
        if not user_text:
            continue
        if user_text in ("/quit", "/exit", "exit", "quit"):
            ui.info("bye")
            return None
        if user_text == "/help":
            _show_help()
            continue
        if user_text in ("/login", "/logout", "/model"):
            if user_text == "/model" and model_switcher:
                new_provider = model_switcher(provider)
                if new_provider is not None:
                    provider = new_provider
                    runtime.configure(
                        provider,
                        runtime.cwd(),
                        lambda prompt, context=None, **kwargs: _run_subagent(provider, prompt, context, **kwargs),
                        session=runtime.session(),
                    )
                continue
            return user_text.lstrip("/")
        if user_text == "/clear":
            messages.clear()
            REGISTRY.reset_state()
            file_state.clear()
            current_tokens = 0
            session_tokens = 0
            if runtime.session():
                runtime.session().append({"type": "event", "event": "clear"})
            ui.info("context cleared")
            continue
        if user_text.startswith("/sessions"):
            _show_sessions(runtime.cwd(), all_projects="--all" in user_text)
            continue
        if user_text.startswith("/resume"):
            query = user_text[len("/resume"):].strip() or None
            new_session = _resume_session(runtime.cwd(), provider, query)
            if new_session is not None:
                session_obj = new_session
                runtime.set_session(new_session)
                messages = new_session.load_messages()
                _restore_tool_state(messages)
                current_tokens = compact.rough_tokens(messages)
                session_tokens = current_tokens
                file_state.clear()
                ui.info(f"resumed {new_session.id} with {len(messages)} message(s)")
            continue
        if user_text == "/compact":
            if len(messages) < 4:
                ui.info("not enough context to compact")
                continue
            try:
                summary, compacted = compact.compact_messages(provider, messages)
                messages[:] = compacted
                current_tokens = compact.rough_tokens(messages)
                if runtime.session():
                    runtime.session().record_compaction(summary, len(messages), messages)
                ui.info(f"compacted context to {len(messages)} message(s)")
            except Exception as e:
                ui.error(f"compact failed: {type(e).__name__}: {e}")
            continue
        if user_text.startswith("/memory"):
            _handle_memory(user_text)
            continue
        if user_text.startswith("/background"):
            _show_background()
            continue
        if user_text == "/doctor":
            ui.info(doctor.run_doctor(runtime.cwd()))
            continue
        if user_text.startswith("/yolo") or user_text == "/safe":
            _handle_yolo(user_text)
            continue
        if user_text == "/thinking":
            on = runtime.set_show_thinking(not runtime.show_thinking())
            ui.info(f"thinking display: {'on' if on else 'off'}")
            continue
        if user_text.startswith("/cwd"):
            arg = user_text[4:].strip()
            if not arg:
                ui.info(f"cwd: {runtime.cwd()}")
                continue
            try:
                new_cwd = runtime.set_cwd(arg)
                ui.workspace_changed(str(new_cwd))
            except Exception as e:
                ui.error(f"{type(e).__name__}: {e}")
            continue
        if user_text == "/status":
            _show_status(provider, current_tokens, session_tokens)
            continue

        checkpoint = len(messages)
        evidence.clear()
        user_msg = {"role": "user", "content": user_text}
        messages.append(user_msg)
        if runtime.session():
            runtime.session().record_message(user_msg)

        try:
            if compact.should_compact(messages, getattr(provider, "context_window", 200_000)):
                ui.info("auto-compacting context before continuing")
                summary, compacted = compact.compact_messages(provider, messages)
                messages[:] = compacted
                current_tokens = compact.rough_tokens(messages)
                if runtime.session():
                    runtime.session().record_compaction(summary, len(messages), messages)
            current_tokens, session_tokens = _run_until_done(
                provider, messages, current_tokens, session_tokens,
            )
        except KeyboardInterrupt:
            del messages[checkpoint:]
            _stub_dangling_tools(messages)
            ui.info("interrupted - turn cancelled")
        except Exception as e:
            del messages[checkpoint:]
            _stub_dangling_tools(messages)
            ui.error(_format_error(e))
            if _is_rate_limit(e) and model_switcher:
                if ui.ask("switch model now?"):
                    new_provider = model_switcher(provider)
                    if new_provider is not None:
                        provider = new_provider
                        runtime.configure(
                            provider,
                            runtime.cwd(),
                    lambda prompt, context=None, **kwargs: _run_subagent(provider, prompt, context, **kwargs),
                            session=runtime.session(),
                        )


def _run_until_done(
    provider: Provider,
    messages: list[dict],
    current_tokens: int,
    session_tokens: int,
    max_turns: int = 50,
    is_subagent: bool = False,
    render: bool = True,
    event_sink: EventSink | None = None,
) -> tuple[int, int]:
    loader = ui.Loader(base_tokens=current_tokens) if render else _SilentLoader()
    if render:
        loader.start()
    try:
        budget = max_turns
        used = 0
        # One-shot per assistant turn: if the response truncates at the
        # default max_tokens cap, retry the SAME call once at the escalated
        # budget before giving up. Mirrors Claude Code's
        # max_output_tokens_escalate transition (query.ts:1199-1221).
        escalated_this_turn = False
        artifact_text_retry_used = False
        artifact_stall_retry_used = False
        artifact_empty_retry_used = False
        orchestration_text_retry_used = False
        tool_failure_retry_used = False
        while used < budget:
            _ensure_tool_result_pairing(messages)
            if not is_subagent:
                shrunk_tokens = _maybe_shrink_context(provider, messages, render=render)
                if shrunk_tokens is not None:
                    current_tokens = shrunk_tokens
            artifact_fast_lane = _artifact_fast_lane_active(messages, is_subagent=is_subagent)
            tools = _tools_for_turn(
                messages,
                is_subagent=is_subagent,
                artifact_fast_lane=artifact_fast_lane,
            )
            tracing.emit(
                "model_turn_start",
                turn=used + 1,
                message_count=len(messages),
                tool_count=len(tools),
                subagent=is_subagent,
            )
            try:
                end = _stream_with_retry(
                    provider,
                    messages,
                    tools,
                    loader,
                    render=render,
                    artifact_fast_lane=artifact_fast_lane,
                    event_sink=event_sink,
                )
            except ReasoningStallError:
                if (
                    not is_subagent
                    and not artifact_stall_retry_used
                    and artifacts.creation_requested(messages)
                ):
                    artifact_stall_retry_used = True
                    correction = artifacts.reasoning_stall_retry_message(messages)
                    messages.append(correction)
                    if runtime.session():
                        runtime.session().append({"type": "message", "message": correction})
                    if render:
                        ui.info("model stalled in hidden reasoning; retrying with immediate file-tool instruction")
                    continue
                raise
            tracing.emit(
                "model_turn_end",
                turn=used + 1,
                stop_reason=end.stop_reason,
                tool_uses=_tool_use_names(end.message),
                usage=end.usage or {},
                subagent=is_subagent,
            )
            if (
                not is_subagent
                and not _has_tool_use(end.message)
                and artifacts.should_retry_empty(messages, end.message)
            ):
                if artifact_empty_retry_used:
                    raise RuntimeError(
                        "provider returned an empty artifact response after retry; "
                        "try a smaller request or a different model"
                    )
                artifact_empty_retry_used = True
                used += 1
                if end.usage:
                    turn = (
                        end.usage.get("input_tokens", 0)
                        + end.usage.get("output_tokens", 0)
                    )
                    current_tokens = turn
                    session_tokens += turn
                correction = artifacts.empty_retry_message(messages)
                messages.append(correction)
                if runtime.session():
                    runtime.session().append({"type": "message", "message": correction})
                tracing.emit("artifact_empty_response_retry", turn=used)
                if render:
                    ui.info("model returned an empty artifact response; retrying with immediate file-tool instruction")
                continue
            messages.append(end.message)
            if runtime.session() and not is_subagent:
                runtime.session().record_message(end.message)
            used += 1

            if end.usage:
                turn = (
                    end.usage.get("input_tokens", 0)
                    + end.usage.get("output_tokens", 0)
                )
                current_tokens = turn
                session_tokens += turn

            if not _has_tool_use(end.message):
                if (
                    not is_subagent
                    and not tool_failure_retry_used
                    and tool_recovery.should_retry_after_tool_failure(messages, end.message)
                ):
                    tool_failure_retry_used = True
                    correction = tool_recovery.recovery_message(messages)
                    messages.append(correction)
                    if runtime.session():
                        runtime.session().append({"type": "message", "message": correction})
                    if render:
                        ui.info("recoverable tool argument failure; retrying with correction instead of stopping")
                    continue
                if (
                    not is_subagent
                    and not orchestration_text_retry_used
                    and orchestrator.should_retry_text_only(messages, end.message)
                ):
                    orchestration_text_retry_used = True
                    correction = orchestrator.tool_retry_message(messages)
                    messages.append(correction)
                    if runtime.session():
                        runtime.session().append({"type": "message", "message": correction})
                    if render:
                        ui.info("repo audit request needs real tool/agent work; retrying with orchestration correction")
                    continue
                if (
                    not is_subagent
                    and not artifact_text_retry_used
                    and artifacts.should_retry_text_only(messages, end.message)
                ):
                    artifact_text_retry_used = True
                    correction = artifacts.tool_retry_message(messages)
                    messages.append(correction)
                    if runtime.session():
                        runtime.session().append({"type": "message", "message": correction})
                    if render:
                        ui.info("model pasted an artifact; retrying with file tools")
                    continue
                if (
                    end.stop_reason == "max_tokens"
                    and not escalated_this_turn
                    and hasattr(provider, "escalate_once")
                ):
                    # Pop the truncated message + restore the budget so this
                    # failed call doesn't count against max_turns. The session
                    # record gets the truncated message; that's intentional —
                    # leaves a forensic trail for /resume.
                    messages.pop()
                    used -= 1
                    new_cap = provider.escalate_once()
                    escalated_this_turn = True
                    if render:
                        ui.info(f"response truncated; retrying at max_tokens={new_cap:,}")
                    continue
                if end.stop_reason == "max_tokens":
                    if render:
                        ui.info("response truncated at escalated cap - rephrase or split work")
                if not is_subagent:
                    note = final_claims.apply_to_message(end.message)
                    if note:
                        tracing.emit("final_claim_guard", note=note)
                        if render and not getattr(end, "text_buffered", False):
                            ui.info(note)
                if not is_subagent:
                    _maybe_complete_todos_after_final(messages)
                if render and getattr(end, "text_buffered", False):
                    _render_buffered_assistant_text(end.message)
                if render:
                    loader.stop()
                if render and not is_subagent:
                    window = getattr(provider, "context_window", 200_000)
                    ctx_pct = min(99, int(current_tokens / window * 100))
                    ui.footer(
                        provider.model, ctx_pct,
                        current_tokens, session_tokens,
                        runtime.cwd(),
                        yolo=runtime.yolo(),
                        approval=runtime.approval_label(),
                    )
                return current_tokens, session_tokens

            precomputed_results = getattr(end, "tool_results", None)
            if precomputed_results is not None:
                _append_tool_results(
                    precomputed_results,
                    messages,
                    record=not is_subagent,
                )
            else:
                _dispatch_tool_uses(
                    provider,
                    end.message,
                    messages,
                    record=not is_subagent,
                    render=render,
                    event_sink=event_sink,
                )
            _ensure_tool_result_pairing(messages)

            if not is_subagent and tool_recovery.should_stop_after_failure_spiral(messages):
                stop_message = tool_recovery.spiral_stop_message(messages)
                messages.append(stop_message)
                if runtime.session():
                    runtime.session().record_message(stop_message)
                if render:
                    ui.error("stopped repeated edit/write tool failures before the task spiraled")
                    loader.stop()
                return current_tokens, session_tokens

            # Micro-compaction: once context is half full, replace stale
            # bodies of re-runnable tool results with a marker. Cheap, no
            # LLM call, runs every turn so big-bash-output sessions don't
            # creep up to the 72% full-compaction threshold unnecessarily.
            window = getattr(provider, "context_window", 200_000)
            approx_tokens = compact.rough_tokens(messages)
            if approx_tokens > window // 3:
                elided = compact.micro_compact(messages, keep_recent=4, min_bytes=2_000)
                if elided and render and not is_subagent:
                    ui.info(f"micro-compacted {elided} stale tool result(s)")
                if elided:
                    current_tokens = compact.rough_tokens(messages)

            # Budget check: instead of dying silently at max_turns, ask the
            # user whether to extend. Subagents just stop at their cap.
            if used >= budget and render and not is_subagent:
                loader.stop()
                if ui.ask(f"used {used} turns on this task - continue for {max_turns} more?"):
                    budget += max_turns
                    loader.start()
                else:
                    break

        _stub_dangling_tools(messages)
        _ensure_tool_result_pairing(messages)
        if render:
            ui.error(f"stopped after {used} turns")
        return current_tokens, session_tokens
    finally:
        if loader.running:
            loader.stop()


def _maybe_shrink_context(provider: Provider, messages: list[dict], *, render: bool) -> int | None:
    """Keep same-task tool loops below provider context limits.

    The top-level loop compacts before a new user turn, but long tool loops can
    grow by hundreds of KB before returning to the prompt. Shrink just before
    each model call so repeated reads/failed edit attempts do not accumulate
    until the provider rejects the request.
    """
    window = getattr(provider, "context_window", 200_000)
    approx = compact.rough_tokens(messages)
    changed = False
    if approx > window // 3:
        elided = compact.micro_compact(messages, keep_recent=4, min_bytes=2_000)
        if elided and render:
            ui.info(f"micro-compacted {elided} stale tool result(s)")
        if elided:
            changed = True
            approx = compact.rough_tokens(messages)

    if compact.should_compact(messages, window, pct=0.68):
        if render:
            ui.info("auto-compacting context before continuing")
        summary, compacted = compact.compact_messages(provider, messages)
        messages[:] = compacted
        if runtime.session():
            runtime.session().record_compaction(summary, len(messages), messages)
        approx = compact.rough_tokens(messages)
        if render:
            ui.info(f"compacted context to {len(messages)} message(s)")
        changed = True
    return approx if changed else None


def _run_subagent(
    provider: Provider,
    prompt: str,
    context: str | None = None,
    *,
    agent_type: str = "explorer",
    write_paths: list[str] | None = None,
    task_id: str | None = None,
    worktree_path: str | None = None,
) -> str:
    state = file_state.snapshot()
    definition = agent_registry.get_agent(agent_type)
    scoped_prompt = agent_registry.build_prompt(
        definition,
        prompt=prompt,
        context=context,
        write_paths=list(write_paths or []),
    )
    messages: list[dict] = [{"role": "user", "content": scoped_prompt}]
    try:
        with runtime.cwd_context(worktree_path):
            with runtime.subagent_context(
                agent_type=definition.name,
                allowed_tools=definition.allowed_tools,
                write_paths=list(write_paths or []),
                task_id=task_id,
            ):
                _run_until_done(provider, messages, 0, 0, is_subagent=True, render=False)
        text = _extract_text(messages[-1] if messages else {})
        if definition.name == "verifier":
            verifiers.record_verifier_output(text, task_id=task_id)
        return text
    finally:
        if definition.read_only:
            file_state.restore(state)


def _stream_one_turn(
    provider: Provider,
    messages: list[dict],
    tools: list[dict],
    loader: ui.Loader,
    *,
    render: bool = True,
    artifact_fast_lane: bool = False,
    event_sink: EventSink | None = None,
) -> TurnEnd:
    show_thinking = runtime.show_thinking()
    thinking_open = False
    thinking_started_at: float | None = None
    thinking_chars = 0
    text_open = False
    buffer_artifact_text = render and artifacts.creation_requested(messages)
    buffered_text: list[str] = []
    streaming_tools = _StreamingToolExecutor(render=render, event_sink=event_sink)
    latest_tool_message: dict | None = None
    stream_started_at = time.monotonic()
    last_event_at: float | None = None
    stream_gap_seconds = _stream_gap_trace_seconds()
    stream_gap_count = 0
    stream_gap_total = 0.0
    if render:
        if buffer_artifact_text:
            ui.activity("waiting for file tool call")
        else:
            ui.activity("waiting for provider response")

    try:
        system_prompt = prompt_builder.build_system_prompt(
            provider_name=getattr(provider, "name", "provider"),
            model=getattr(provider, "model", "model"),
            cwd=runtime.cwd(),
            tool_guidance=REGISTRY.prompts(only={str(tool.get("name", "")) for tool in tools}),
            turn_guidance=_turn_guidance(messages, artifact_fast_lane=artifact_fast_lane),
        )
        for event in provider.stream_turn(messages, tools, system_prompt):
            event_at = time.monotonic()
            if last_event_at is None:
                tracing.emit(
                    "stream_first_event",
                    ttft_seconds=round(event_at - stream_started_at, 3),
                    event_type=type(event).__name__,
                )
            else:
                gap = event_at - last_event_at
                if stream_gap_seconds > 0 and gap >= stream_gap_seconds:
                    stream_gap_count += 1
                    stream_gap_total += gap
                    tracing.emit(
                        "stream_gap",
                        gap_seconds=round(gap, 3),
                        gap_count=stream_gap_count,
                        total_gap_seconds=round(stream_gap_total, 3),
                        event_type=type(event).__name__,
                    )
            last_event_at = event_at
            streaming_tools.poll()
            if isinstance(event, ThinkingDelta):
                if thinking_started_at is None:
                    thinking_started_at = event_at
                thinking_chars += len(event.text or "")
                if show_thinking:
                    _emit_event(event_sink, {"event": "thinkingDelta", "text": event.text})
                if _reasoning_stalled(
                    thinking_started_at,
                    thinking_chars,
                    artifact=buffer_artifact_text,
                    now=event_at,
                ):
                    raise ReasoningStallError(
                        "provider spent too long in reasoning without producing text or tool calls. "
                        "Retry with thinking disabled, a faster model, or a smaller request."
                    )
                if render:
                    if show_thinking:
                        ui.activity("receiving reasoning stream")
                        ui.stream_delta("reasoning", event.text)
                    else:
                        if buffer_artifact_text:
                            ui.stream_delta(
                                "thinking",
                                event.text,
                                activity="planning file tool call",
                            )
                        else:
                            ui.stream_delta(
                                "thinking",
                                event.text,
                                activity="model planning before next action",
                            )
                if not render or not show_thinking:
                    continue
                if not thinking_open:
                    ui.thinking_start()
                    thinking_open = True
                ui.thinking_chunk(event.text)
            elif isinstance(event, ToolUseProgress):
                thinking_started_at = None
                _emit_event(
                    event_sink,
                    {
                        "event": "toolProgress",
                        "tool": event.name,
                        "callId": event.call_id,
                        "argumentChars": event.argument_chars,
                        "text": _tool_progress_detail(event),
                    },
                )
                if render:
                    ui.activity(f"receiving tool args: {event.name}")
                    ui.tool_progress(
                        event.name,
                        argument_chars=event.argument_chars,
                        call_id=event.call_id,
                        detail=_tool_progress_detail(event),
                        preview=_tool_progress_preview(event),
                    )
            elif isinstance(event, TextDelta):
                thinking_started_at = None
                _emit_event(event_sink, {"event": "assistantDelta", "text": event.text})
                if not render:
                    continue
                ui.activity("receiving text stream")
                ui.stream_delta("text", event.text)
                if buffer_artifact_text:
                    if thinking_open:
                        ui.thinking_end()
                        thinking_open = False
                    buffered_text.append(event.text)
                    partial = "".join(buffered_text)
                    if artifacts.looks_like_artifact_start(partial):
                        return TurnEnd(
                            stop_reason="text_artifact",
                            message={
                                "role": "assistant",
                                "content": [{"type": "text", "text": partial}],
                            },
                            text_buffered=True,
                        )
                    continue
                if not text_open and not event.text.strip():
                    continue
                if thinking_open:
                    ui.thinking_end()
                    thinking_open = False
                if not text_open:
                    ui.assistant_start()
                    text_open = True
                ui.assistant_chunk(event.text)
            elif isinstance(event, ToolUseReady):
                if _has_tool_use(event.message):
                    latest_tool_message = event.message
                if event.tool:
                    streaming_tools.add(event.tool)
                if render:
                    ui.activity("tool call ready")
                    ui.stream_clear()
                    ui.tool_progress_clear()
                if thinking_open:
                    ui.thinking_end()
                    thinking_open = False
                if text_open:
                    ui.assistant_end()
                    text_open = False
            elif isinstance(event, TurnEnd):
                for block in _tool_blocks(event.message):
                    streaming_tools.add(block)
                if render:
                    ui.activity("response complete")
                    ui.stream_clear()
                    ui.tool_progress_clear()
                if thinking_open:
                    ui.thinking_end()
                if text_open:
                    ui.assistant_end()
                if buffered_text and _extract_text(event.message):
                    event.text_buffered = True
                if _has_tool_use(event.message):
                    event.tool_results = streaming_tools.finish()
                _emit_stream_gap_summary(stream_gap_count, stream_gap_total)
                return event

        _emit_stream_gap_summary(stream_gap_count, stream_gap_total)
        raise RuntimeError("provider stream ended without a TurnEnd event")

    except Exception as exc:
        if latest_tool_message and _has_tool_use(latest_tool_message):
            if render:
                ui.activity("stream ended after tool call")
                ui.stream_clear()
                ui.tool_progress_clear()
            if thinking_open:
                ui.thinking_end()
                thinking_open = False
            if text_open:
                ui.assistant_end()
                text_open = False
            if render:
                ui.info(
                    "provider stream ended after a tool call; "
                    "continuing with paired tool result"
                )
            recovered = TurnEnd(
                stop_reason="tool_use",
                message=latest_tool_message,
                usage=None,
            )
            recovered.tool_results = streaming_tools.finish()
            tracing.emit(
                "stream_recovered_after_tool_use",
                error=f"{type(exc).__name__}: {exc}",
                tool_uses=_tool_use_names(latest_tool_message),
            )
            _emit_stream_gap_summary(stream_gap_count, stream_gap_total)
            return recovered
        _emit_stream_gap_summary(stream_gap_count, stream_gap_total)
        streaming_tools.cancel()
        if render:
            ui.stream_clear()
            ui.tool_progress_clear()
        if thinking_open:
            ui.thinking_end()
        if text_open:
            ui.assistant_end()
        raise

    except BaseException:
        _emit_stream_gap_summary(stream_gap_count, stream_gap_total)
        streaming_tools.cancel()
        if render:
            ui.stream_clear()
            ui.tool_progress_clear()
        if thinking_open:
            ui.thinking_end()
        if text_open:
            ui.assistant_end()
        raise


class _SilentLoader:
    running = False

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


_ARTIFACT_FAST_LANE_BLOCKED_TOOLS = {
    "agent_output",
    "ask_user",
    "cleanup_agent",
    "list_agents",
    "present_plan",
    "send_agent_message",
    "spawn_agent",
    "stop_agent",
    "todos",
}


def _tools_for_turn(
    messages: list[dict],
    *,
    is_subagent: bool,
    artifact_fast_lane: bool | None = None,
) -> list[dict]:
    tools = REGISTRY.schemas(for_subagent=is_subagent)
    if artifact_fast_lane is None:
        artifact_fast_lane = _artifact_fast_lane_active(messages, is_subagent=is_subagent)
    if artifact_fast_lane:
        tools = [
            tool
            for tool in tools
            if str(tool.get("name", "")) not in _ARTIFACT_FAST_LANE_BLOCKED_TOOLS
        ]
    return tools


def _artifact_fast_lane_active(messages: list[dict], *, is_subagent: bool) -> bool:
    if is_subagent or not artifacts.creation_requested(messages):
        return False
    successful = artifacts.successful_tool_names_since_last_request(messages)
    return not successful.intersection({"write_file", "edit_file", "multi_edit"})


def _turn_guidance(messages: list[dict], *, artifact_fast_lane: bool) -> str:
    chunks: list[str] = []
    orch = orchestrator.guidance_for_turn(messages)
    if orch:
        chunks.append(orch)
    if artifact_fast_lane:
        chunks.append(artifacts.fast_lane_system_guidance(messages))
    return "\n\n".join(chunks)


def _dispatch_tool_uses(
    provider: Provider,
    assistant_msg: dict,
    messages: list[dict],
    record: bool = True,
    render: bool = True,
    event_sink: EventSink | None = None,
) -> None:
    results: list[dict] = []
    tool_blocks = [
        block
        for block in assistant_msg.get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]
    if _can_dispatch_parallel(tool_blocks):
        # OAuth limits concurrency strictly (often 1 or 2); sequential is safer
        # to avoid generic 429s.
        if provider.is_oauth:
            if render:
                ui.info("sequential execution: OAuth concurrency is restricted")
            for block in tool_blocks:
                ok, output = _dispatch_one(block, render=render, event_sink=event_sink)
                results.append(_tool_result_block(block, ok, output))
        else:
            results = _dispatch_parallel(tool_blocks, render=render, event_sink=event_sink)
    else:
        for idx, block in enumerate(tool_blocks):
            if render:
                ui.activity(f"executing tool: {block.get('name', 'tool')}")
            ok, output = _dispatch_one(block, render=render, event_sink=event_sink)
            results.append(_tool_result_block(block, ok, output))
            if _should_abort_tool_batch(ok, output):
                skipped = tool_blocks[idx + 1:]
                for pending in skipped:
                    skipped_result = _skipped_tool_result(pending)
                    results.append(skipped_result)
                    _emit_event(
                        event_sink,
                        {
                            "event": "toolResult",
                            "tool": str(pending.get("name") or "tool"),
                            "callId": str(pending.get("id") or ""),
                            "ok": False,
                            "text": _event_text_preview(skipped_result.get("content", "")),
                        },
                    )
                if skipped and render:
                    ui.info(f"skipped {len(skipped)} queued tool call(s) after failure")
                break
    if not results:
        raise RuntimeError("assistant stopped for tool_use without tool_use blocks")
    result_msg = {"role": "user", "content": results}
    messages.append(result_msg)
    if record and runtime.session():
        runtime.session().record_message(result_msg)


def _append_tool_results(
    results: list[dict],
    messages: list[dict],
    *,
    record: bool,
) -> None:
    if not results:
        raise RuntimeError("assistant stopped for tool_use without tool_use blocks")
    result_msg = {"role": "user", "content": results}
    messages.append(result_msg)
    if record and runtime.session():
        runtime.session().record_message(result_msg)


@dataclass
class _RunningTool:
    block: dict
    future: Future
    parallel_safe: bool


class _StreamingToolExecutor:
    """Claude-style streamed tool executor.

    Tool input still has to finish streaming before execution can begin, but
    once a tool block closes we can start safe/auto-approved tools while the
    provider continues sending later blocks and message_stop.
    """

    def __init__(self, *, render: bool, event_sink: EventSink | None = None) -> None:
        self._render = render
        self._event_sink = event_sink
        self._queue: list[dict] = []
        self._order: list[dict] = []
        self._running: dict[str, _RunningTool] = {}
        self._results: dict[str, dict] = {}
        self._seen: set[str] = set()
        self._pool: ThreadPoolExecutor | None = None
        self._aborted = False

    def add(self, block: dict) -> None:
        tool_id = str(block.get("id") or "")
        if not tool_id or tool_id in self._seen:
            return
        self._seen.add(tool_id)
        self._order.append(block)
        self._queue.append(block)
        _emit_event(
            self._event_sink,
            {
                "event": "toolCall",
                "tool": str(block.get("name") or "tool"),
                "callId": tool_id,
                "args": block.get("input") if isinstance(block.get("input"), dict) else None,
                "text": _tool_summary(block),
            },
        )
        self._pump()

    def finish(self) -> list[dict]:
        while self._queue or self._running:
            self._pump()
            if self._queue and not self._running:
                block = self._queue.pop(0)
                if self._aborted:
                    skipped = _skipped_tool_result(block)
                    self._results[str(block.get("id") or "")] = skipped
                    _emit_event(
                        self._event_sink,
                        {
                            "event": "toolResult",
                            "tool": str(block.get("name") or "tool"),
                            "callId": str(block.get("id") or ""),
                            "ok": False,
                            "text": _event_text_preview(skipped.get("content", "")),
                        },
                    )
                    continue
                ok, output = _dispatch_one(block, render=self._render, event_sink=self._event_sink)
                self._results[str(block.get("id") or "")] = _tool_result_block(block, ok, output)
                if _should_abort_tool_batch(ok, output):
                    self._aborted = True
                continue
            self._complete_finished(wait_for_one=True)
        self._shutdown()
        return [self._results[str(block.get("id") or "")] for block in self._order]

    def cancel(self) -> None:
        for running in self._running.values():
            running.future.cancel()
        self._queue.clear()
        self._shutdown(wait_for_running=False)

    def poll(self) -> None:
        self._complete_finished(wait_for_one=False)
        self._pump()

    def _pump(self) -> None:
        self._complete_finished(wait_for_one=False)
        while self._queue and not self._aborted:
            block = self._queue[0]
            if not self._can_stream_dispatch(block):
                return
            parallel_safe = _tool_parallel_safe(block)
            if not self._can_start(parallel_safe):
                return
            self._queue.pop(0)
            self._start(block, parallel_safe)

    def _start(self, block: dict, parallel_safe: bool) -> None:
        tool_id = str(block.get("id") or "")
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=8)
        if self._render:
            ui.tool_progress_clear()
            ui.tool_begin(tool_id, str(block.get("name") or "tool"), _tool_summary(block))
            ui.tool_set_state(tool_id, "running")
        context = contextvars.copy_context()
        future = self._pool.submit(
            context.run,
            _dispatch_one,
            block,
            render=False,
            event_sink=self._event_sink,
        )
        self._running[tool_id] = _RunningTool(block=block, future=future, parallel_safe=parallel_safe)

    def _complete_finished(self, *, wait_for_one: bool) -> None:
        if wait_for_one and self._running and not any(item.future.done() for item in self._running.values()):
            wait([item.future for item in self._running.values()], return_when=FIRST_COMPLETED)
        finished = [
            tool_id
            for tool_id, item in self._running.items()
            if item.future.done()
        ]
        for tool_id in finished:
            item = self._running.pop(tool_id)
            try:
                ok, output = item.future.result()
            except Exception as exc:
                ok, output = False, f"{type(exc).__name__}: {exc}"
                _emit_event(
                    self._event_sink,
                    {
                        "event": "toolResult",
                        "tool": str(item.block.get("name") or "tool"),
                        "callId": tool_id,
                        "ok": False,
                        "text": _event_text_preview(output),
                    },
                )
            self._results[tool_id] = _tool_result_block(item.block, ok, output)
            if self._render:
                ui.tool_end(tool_id, ok=ok, output=str(output))
            if _should_abort_tool_batch(ok, str(output)):
                self._aborted = True

    def _can_start(self, parallel_safe: bool) -> bool:
        if not self._running:
            return True
        return parallel_safe and all(item.parallel_safe for item in self._running.values())

    def _can_stream_dispatch(self, block: dict) -> bool:
        tool = REGISTRY.get(str(block.get("name") or ""))
        if tool is None or tool.quiet:
            return False
        if tool.name in _FOREGROUND_ONLY_TOOLS:
            return False
        args = block.get("input") or {}
        if not isinstance(args, dict):
            return False
        try:
            classification = tool.classify(args) if tool.classify else None
        except Exception:
            classification = None
        if classification == "danger":
            return False
        if classification == "safe":
            return True
        if runtime.can_auto_approve(tool.name):
            return True
        return tool.name in _STREAM_AUTO_TOOLS

    def _shutdown(self, *, wait_for_running: bool = True) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=wait_for_running, cancel_futures=not wait_for_running)
            self._pool = None


def _tool_blocks(message: dict) -> list[dict]:
    return [
        block
        for block in message.get("content", [])
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


_STREAM_AUTO_TOOLS = {
    "bash_poll",
    "git",
    "glob",
    "grep",
    "list_files",
    "read_file",
    "read_media",
}


_FOREGROUND_ONLY_TOOLS = {
    "ask_user",
    "present_plan",
    "set_workspace",
    "spawn_agent",
}


def _tool_summary(block: dict) -> str:
    tool = REGISTRY.get(str(block.get("name") or ""))
    args = block.get("input") if isinstance(block.get("input"), dict) else {}
    if tool and tool.summary:
        try:
            return tool.summary(args)
        except Exception:
            pass
    return json.dumps(args, ensure_ascii=False)[:120] if args else ""


def _tool_parallel_safe(block: dict) -> bool:
    tool = REGISTRY.get(str(block.get("name") or ""))
    return bool(tool and tool.parallel_safe)


def _skipped_tool_result(block: dict) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": block["id"],
        "content": (
            "skipped: previous tool failed or was denied. "
            "Read the failure/feedback and choose the next step."
        ),
        "is_error": True,
    }


def _tool_progress_detail(event: ToolUseProgress) -> str:
    partial = event.partial_json or ""
    if not partial:
        return "tool call opened"
    parsed = _partial_tool_args(partial)
    if event.name in {"write_file", "edit_file"}:
        path = str(parsed.get("path") or "")
        content = str(parsed.get("content") or parsed.get("new") or "")
        if content:
            lines = content.count("\n") + 1
            label = f"{lines} line(s), {len(content):,} chars"
        else:
            label = f"{len(partial):,} arg chars"
        return f"{path} - {label}" if path else label
    if event.name == "multi_edit":
        path = str(parsed.get("path") or "")
        edits = parsed.get("edits")
        if isinstance(edits, list):
            label = f"{len(edits)} edit(s)"
        else:
            label = f"{len(partial):,} arg chars"
        return f"{path} - {label}" if path else label
    if event.name == "bash_start":
        cmd = str(parsed.get("command") or "")
        return cmd[:120] if cmd else f"{len(partial):,} arg chars"
    return f"{len(partial):,} arg chars"


def _tool_progress_preview(event: ToolUseProgress) -> list[str]:
    if event.name not in {"write_file", "edit_file"} or not event.partial_json:
        return []
    parsed = _partial_tool_args(event.partial_json)
    content = str(parsed.get("content") or parsed.get("new") or "")
    if not content:
        return []
    lines = [line.rstrip() for line in content.splitlines() if line.strip()]
    if not lines:
        return []
    return lines[-3:]


def _partial_tool_args(partial: str) -> dict:
    try:
        value = json.loads(partial)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass
    out: dict[str, str] = {}
    for key in ("path", "command", "content", "new"):
        value = _partial_json_string_value(partial, key)
        if value:
            out[key] = value
    return out


def _partial_json_string_value(text: str, key: str) -> str:
    marker = f'"{key}"'
    idx = text.find(marker)
    if idx < 0:
        return ""
    colon = text.find(":", idx + len(marker))
    if colon < 0:
        return ""
    start = text.find('"', colon + 1)
    if start < 0:
        return ""
    chars: list[str] = []
    escaped = False
    for ch in text[start + 1:]:
        if escaped:
            chars.append(_unescape_json_char(ch))
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            break
        chars.append(ch)
    return "".join(chars)


def _unescape_json_char(ch: str) -> str:
    return {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
    }.get(ch, ch)


def _can_dispatch_parallel(tool_blocks: list[dict]) -> bool:
    if len(tool_blocks) < 2:
        return False
    for block in tool_blocks:
        tool = REGISTRY.get(block.get("name", ""))
        if tool is None or not tool.parallel_safe:
            return False
    return True


def _dispatch_parallel(
    tool_blocks: list[dict],
    *,
    render: bool,
    event_sink: EventSink | None = None,
) -> list[dict]:
    workers = min(8, len(tool_blocks))
    if render:
        names = ", ".join(str(block.get("name", "")) for block in tool_blocks)
        ui.activity(f"executing tools: {names}")
        ui.info(f"running {len(tool_blocks)} parallel-safe tool calls: {names}")

    def run_one(block: dict) -> dict:
        ok, output = _dispatch_one(block, render=False, event_sink=event_sink)
        return _tool_result_block(block, ok, output)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(contextvars.copy_context().run, run_one, block)
            for block in tool_blocks
        ]
        results = [future.result() for future in futures]
    if render:
        failures = sum(1 for item in results if item.get("is_error"))
        suffix = f" ({failures} failed)" if failures else ""
        ui.info(f"parallel tool calls complete{suffix}")
    return results


def _dispatch_one(
    block: dict,
    *,
    render: bool,
    event_sink: EventSink | None = None,
) -> tuple[bool, str]:
    tool_name = str(block.get("name", ""))
    tool_id = str(block.get("id", ""))
    args = block.get("input") or {}
    _emit_event(
        event_sink,
        {
            "event": "toolStarted",
            "tool": tool_name,
            "callId": tool_id,
            "args": args if isinstance(args, dict) else None,
            "text": _tool_summary(block),
        },
    )
    tracing.emit("tool_start", tool_id=tool_id, tool=tool_name, args=args)
    started = time.perf_counter()
    ok, output = dispatch(
        tool_name,
        args,
        render=render,
        tool_use_id=tool_id if render else "",
    )
    tracing.emit(
        "tool_end",
        tool_id=tool_id,
        tool=tool_name,
        ok=ok,
        duration_ms=int((time.perf_counter() - started) * 1000),
        output=str(output)[:1000],
    )
    _emit_event(
        event_sink,
        {
            "event": "toolResult",
            "tool": tool_name,
            "callId": tool_id,
            "ok": ok,
            "text": _event_text_preview(output),
        },
    )
    return ok, output


def _tool_result_block(block: dict, ok: bool, output) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": block["id"],
        "content": output,
        "is_error": not ok,
    }


def _should_abort_tool_batch(ok: bool, output: str) -> bool:
    if ok:
        return False
    text = str(output)
    return (
        text.startswith("denied by user")
        or text.startswith("PermissionError:")
        or text.startswith("schema validation failed:")
        or text.startswith("ValueError: multi_edit aborted")
    )


_TRANSIENT_NAMES = {
    "RateLimitError",
    "InternalServerError",
    "APIConnectionError",
    "APITimeoutError",
    "ServiceUnavailableError",
    "OverloadedError",
    "ResponseError",
}
_TRANSIENT_HINTS = (
    "overloaded", "rate limit", "rate_limit",
    "503", "502", "504",
    "timeout", "timed out", "connection", "temporarily",
)


def _is_transient(exc: Exception) -> bool:
    if type(exc).__name__ in _TRANSIENT_NAMES:
        return True
    msg = str(exc).lower()
    return any(h in msg for h in _TRANSIENT_HINTS)


def _is_rate_limit(exc: Exception) -> bool:
    return type(exc).__name__ == "RateLimitError" or "rate limit" in str(exc).lower()


def _stream_with_retry(
    provider: Provider,
    messages: list[dict],
    tools: list[dict],
    loader: ui.Loader,
    delays: tuple[int, ...] = (2, 5, 12),
    *,
    render: bool = True,
    artifact_fast_lane: bool = False,
    event_sink: EventSink | None = None,
) -> TurnEnd:
    """Run one turn; on transient failure, back off and retry. The live
    region stays running across retries — the wait just shows above it."""
    last_err: Exception | None = None
    for attempt in range(len(delays) + 1):
        try:
            return _stream_one_turn(
                provider,
                messages,
                tools,
                loader,
                render=render,
                artifact_fast_lane=artifact_fast_lane,
                event_sink=event_sink,
            )
        except Exception as e:
            last_err = e
            if _is_rate_limit(e):
                raise
            if not _is_transient(e) or attempt == len(delays):
                raise
            wait = delays[attempt]
            if render:
                ui.info(
                    f"transient {type(e).__name__} - retry "
                    f"{attempt + 1}/{len(delays)} in {wait}s"
                )
            time.sleep(wait)
    raise last_err  # pragma: no cover (unreachable)


def _reasoning_stalled(
    started_at: float,
    chars: int,
    *,
    artifact: bool = False,
    now: float | None = None,
) -> bool:
    if runtime.show_thinking():
        return False
    seconds = _reasoning_stall_seconds(artifact=artifact)
    if seconds <= 0:
        return False
    current = time.monotonic() if now is None else now
    return chars > 0 and (current - started_at) >= seconds


def _reasoning_stall_seconds(*, artifact: bool) -> int:
    base = _env_int("CRYPT_REASONING_STALL_SECONDS", 90)
    if not artifact:
        return base
    return _env_int("CRYPT_ARTIFACT_REASONING_STALL_SECONDS", max(base, 120))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _stream_gap_trace_seconds() -> int:
    return _env_int("CRYPT_STREAM_GAP_TRACE_SECONDS", 30)


def _emit_stream_gap_summary(count: int, total_seconds: float) -> None:
    if count <= 0:
        return
    tracing.emit(
        "stream_gap_summary",
        gap_count=count,
        total_gap_seconds=round(total_seconds, 3),
    )


def _has_tool_use(msg: dict) -> bool:
    return any(
        isinstance(b, dict) and b.get("type") == "tool_use"
        for b in msg.get("content", [])
    )


def _tool_use_names(msg: dict) -> list[str]:
    return [
        str(b.get("name", ""))
        for b in msg.get("content", [])
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]


def _ensure_tool_result_pairing(messages: list[dict]) -> None:
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        expected = [
            b["id"] for b in msg.get("content", [])
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")
        ]
        if not expected:
            continue
        if i + 1 >= len(messages):
            raise RuntimeError("assistant tool_use has no following tool_result message")
        nxt = messages[i + 1]
        if nxt.get("role") != "user" or not isinstance(nxt.get("content"), list):
            raise RuntimeError("assistant tool_use must be followed by user tool_result blocks")
        actual = [
            b.get("tool_use_id") for b in nxt["content"]
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]
        if sorted(expected) != sorted(actual):
            raise RuntimeError(
                "tool_result ids do not match tool_use ids: "
                f"expected {expected}, got {actual}"
            )


def _extract_text(message: dict) -> str:
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def _maybe_complete_todos_after_final(messages: list[dict]) -> None:
    try:
        from tools import todos

        current = todos.get_todos()
        if not current or all(item.get("status") == "done" for item in current):
            return
        if not artifacts.creation_requested(messages):
            return
        successful = artifacts.successful_tool_names_since_last_request(messages)
        if successful.intersection({"write_file", "edit_file", "multi_edit", "open_file"}):
            todos.complete_all()
    except Exception:
        return

def _render_buffered_assistant_text(message: dict) -> None:
    text = _extract_text(message)
    if not text:
        return
    ui.assistant_start()
    ui.assistant_chunk(text)
    ui.assistant_end()


def _stub_dangling_tools(messages: list[dict]) -> None:
    if not messages or messages[-1].get("role") != "assistant":
        return
    tool_ids = [
        b["id"] for b in messages[-1].get("content", [])
        if b.get("type") == "tool_use"
    ]
    if tool_ids:
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": "cancelled: max turns exceeded",
                    "is_error": True,
                }
                for tid in tool_ids
            ],
        })


def _show_help() -> None:
    ui.info("/quit              exit crypt")
    ui.info("/help              this message")
    ui.info("/status            show provider, auth, tools, todos")
    ui.info("/sessions [--all]  list resumable sessions")
    ui.info("/resume [id|text]  resume latest or matching session")
    ui.info("/compact           summarize old context and keep working")
    ui.info("/memory            show durable Crypt memory")
    ui.info("/memory add <txt>  save durable memory")
    ui.info("/background        list background shell jobs")
    ui.info("/doctor            run local Crypt harness self-checks")
    ui.info("/model             switch provider/model in this session")
    ui.info("/login   /logout   swap or sign out of Anthropic OAuth")
    ui.info("/clear             wipe context and todos")
    ui.info("/yolo              auto-approve file edits only")
    ui.info("/yolo all          auto-approve every tool (dangerous)")
    ui.info("/yolo off /safe    return to manual approvals")
    ui.info("/thinking          toggle thinking display")
    ui.info("/cwd [path]        show or move workspace")


def _restore_tool_state(messages: list[dict]) -> None:
    try:
        from tools.todos import run as todos_run
    except Exception:
        return
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == "todos"
                and isinstance(block.get("input"), dict)
            ):
                todos_run(block["input"])
                return


def _show_sessions(cwd: str, all_projects: bool = False) -> None:
    infos = sessions.list_sessions(cwd, all_projects=all_projects)
    if not infos:
        ui.info("no sessions found")
        return
    rows = {}
    for info in infos[:12]:
        age = time.strftime("%Y-%m-%d %H:%M", time.localtime(info.updated_at or info.created_at))
        label = info.session_id[:8]
        rows[label] = f"{age} · {info.title or '(untitled)'} · {info.message_count} messages"
    ui.status_panel(rows)


def _resume_session(cwd: str, provider: Provider, query: str | None):
    info = sessions.find_session(cwd, query)
    if info is None:
        ui.info("no matching session found")
        return None
    return sessions.load_session(
        info.cwd or cwd,
        info.session_id,
        provider=getattr(provider, "name", ""),
        model=getattr(provider, "model", ""),
    )


def _handle_memory(command: str) -> None:
    arg = command[len("/memory"):].strip()
    try:
        if not arg:
            ui.status_panel({"memory": memory.MEMORY_INDEX, "content": memory.read_memory(4000)})
            return
        if arg.startswith("add "):
            ui.info(memory.add_memory(arg[4:].strip()))
            return
        if arg.startswith("search "):
            needle = arg[len("search "):].strip().lower()
            lines = [line for line in memory.read_memory(80_000).splitlines() if needle in line.lower()]
            ui.info("\n".join(lines) if lines else "(no matches)")
            return
        ui.info("usage: /memory, /memory add <text>, /memory search <text>")
    except Exception as e:
        ui.error(f"memory failed: {type(e).__name__}: {e}")


def _show_background() -> None:
    jobs = background.list_jobs()
    if not jobs:
        ui.info("no background jobs")
        return
    rows = {
        job.id: f"{background.status(job)} · {job.command} · {job.output_path}"
        for job in jobs
    }
    ui.status_panel(rows)


def _handle_yolo(command: str) -> None:
    arg = command[5:].strip().lower() if command.startswith("/yolo") else "off"
    if command == "/safe" or arg in ("off", "false", "0", "manual"):
        mode = runtime.set_approval_mode(runtime.APPROVAL_NORMAL)
    elif arg in ("all", "full", "danger"):
        mode = runtime.set_approval_mode(runtime.APPROVAL_ALL)
    elif arg in ("", "edit", "edits", "trusted"):
        current = runtime.approval_mode()
        next_mode = (
            runtime.APPROVAL_NORMAL
            if current == runtime.APPROVAL_EDITS
            else runtime.APPROVAL_EDITS
        )
        mode = runtime.set_approval_mode(next_mode)
    else:
        ui.info("usage: /yolo, /yolo all, /yolo off")
        return

    label = runtime.approval_label()
    if mode == runtime.APPROVAL_EDITS:
        ui.info("approval: auto-work (non-danger shell and file edits skip prompts)")
    elif mode == runtime.APPROVAL_ALL:
        ui.info("approval: yolo-all (all tool prompts bypassed)")
    else:
        ui.info(f"approval: {label}")


def _show_status(provider: Provider, current_tokens: int, session_tokens: int) -> None:
    from core import auth
    from tools.todos import get_todos

    cred = auth.resolve()
    todos = get_todos()
    done = sum(1 for t in todos if t.get("status") == "done")
    doing = sum(1 for t in todos if t.get("status") == "doing")
    pending = sum(1 for t in todos if t.get("status") == "pending")
    window = getattr(provider, "context_window", 200_000)
    ctx_pct = min(99, int(current_tokens / window * 100)) if current_tokens else 0

    auth_line = "none"
    if cred:
        if cred.kind == "oauth":
            auth_line = f"oauth · {cred.email or 'Anthropic OAuth'}"
            if cred.plan:
                auth_line += f" · {cred.plan}"
        else:
            auth_line = cred.kind

    ui.status_panel({
        "provider": provider.name,
        "model": provider.model,
        "auth": auth_line,
        "cwd": runtime.cwd(),
        "approval": runtime.approval_label(),
        "thinking": "on" if runtime.show_thinking() else "off",
        "tools": f"{len(REGISTRY.schemas())} loaded",
        "todos": f"{done} done · {doing} doing · {pending} pending" if todos else "none",
        "session_id": runtime.session_id() or "none",
        "background": f"{len(background.list_jobs())} job(s)",
        "context": f"{ctx_pct}% ({current_tokens:,} / {window:,})",
        "session": f"{session_tokens:,} tokens",
    })


def _format_error(exc: Exception) -> str:
    name = type(exc).__name__
    if name == "RateLimitError":
        return _rate_limit_help(exc)
    if _is_transient(exc):
        return (
            f"{name}: {exc}\n"
            "   Provider is overloaded or unreachable. Tried with backoff. "
            "Use /model to switch provider/model, or wait a minute and retry."
        )
    return f"{name}: {exc}"


# Header names from `services/rateLimitMocking.ts` and `services/claudeAiLimits.ts`
# in the Claude Code reference. Anthropic returns these on every response (not
# just 429s); the unified-* family is the Claude.ai 5h/7d window quota, which
# is what OAuth users almost always trip on.
_RATE_HEADERS = (
    "anthropic-ratelimit-unified-status",
    "anthropic-ratelimit-unified-5h-status",
    "anthropic-ratelimit-unified-5h-resets-at",
    "anthropic-ratelimit-unified-5h-utilization",
    "anthropic-ratelimit-unified-7d-status",
    "anthropic-ratelimit-unified-7d-resets-at",
    "anthropic-ratelimit-unified-7d-utilization",
    "retry-after",
)


def _rate_limit_help(exc: Exception) -> str:
    """Inspect Anthropic response headers to give a real diagnosis instead of
    blanket-blaming max_tokens. Handles two header families:
      - Claude.ai unified-* (OAuth, 5h/7d windows)
      - Standard API per-minute (requests / tokens / input-tokens / output-tokens)
    Falls back to a raw header dump if we see rate-limit shaped headers we
    don't recognize, so we can debug instead of guessing."""
    headers = _extract_headers(exc)
    name = type(exc).__name__
    parts: list[str] = [f"{name}: {exc}"]
    found_anything = False
    saw_exhausted_window = False

    # Family 1: Claude.ai unified windows (OAuth users). A status of "rejected"
    # or "exceeded" means that window's quota is gone — only the clock fixes it.
    unified_status = headers.get("anthropic-ratelimit-unified-status")
    if unified_status:
        found_anything = True
        parts.append(f"   unified status: {unified_status}")
        if unified_status.lower() in ("rejected", "exceeded"):
            saw_exhausted_window = True

    for tag, label in (("5h", "5-hour"), ("7d", "7-day")):
        status = (headers.get(f"anthropic-ratelimit-unified-{tag}-status") or "").lower()
        if not status:
            continue
        found_anything = True
        util = headers.get(f"anthropic-ratelimit-unified-{tag}-utilization")
        resets_at = headers.get(f"anthropic-ratelimit-unified-{tag}-resets-at")
        try:
            util_pct = f"{float(util) * 100:.0f}%" if util else "?"
        except ValueError:
            util_pct = "?"
        when = _format_reset(resets_at)
        parts.append(
            f"   {label} window: {status}, ~{util_pct} used"
            + (f", resets {when}" if when else "")
        )
        if status in ("rejected", "exceeded"):
            saw_exhausted_window = True

    # Family 2: standard API per-minute rate limits (API-key users, but also
    # surfaces on OAuth when the unified family isn't populated).
    for kind, label in (
        ("requests", "requests/min"),
        ("input-tokens", "input tok/min"),
        ("output-tokens", "output tok/min"),
        ("tokens", "tokens/min"),
    ):
        limit = headers.get(f"anthropic-ratelimit-{kind}-limit")
        remaining = headers.get(f"anthropic-ratelimit-{kind}-remaining")
        reset = headers.get(f"anthropic-ratelimit-{kind}-reset")
        if limit is None and remaining is None:
            continue
        found_anything = True
        when = _format_reset(reset) if reset else ""
        parts.append(
            f"   {label}: {remaining or '?'}/{limit or '?'} remaining"
            + (f", resets {when}" if when else "")
        )

    retry_after = headers.get("retry-after")
    if retry_after:
        found_anything = True
        try:
            secs = int(float(retry_after))
            parts.append(f"   server suggests retry in {secs}s")
        except ValueError:
            parts.append(f"   server suggests retry-after: {retry_after}")

    # If we recognized nothing but rate-limit-shaped headers exist, dump them
    # raw so we can see what we're actually dealing with instead of guessing.
    if not found_anything:
        rl_keys = sorted(
            k for k in headers
            if any(h in k for h in ("ratelimit", "retry-after", "quota", "limit"))
        )
        if rl_keys:
            parts.append("   unrecognized rate-limit headers (raw):")
            for k in rl_keys[:12]:
                parts.append(f"     {k}: {headers[k]}")
        elif headers:
            # If we still found nothing but headers exist, dump some basics.
            parts.append("   no rate-limit headers found. debug headers:")
            for k in sorted(headers.keys())[:8]:
                parts.append(f"     {k}: {headers[k]}")

    if saw_exhausted_window:
        parts.append(
            "   Claude.ai window is exhausted; only the clock fixes this. "
            "Reducing --max-tokens won't help."
        )
    parts.append("   Use /model to switch to Ollama Cloud, or wait it out.")
    return "\n".join(parts)


def _extract_headers(exc: Exception) -> dict[str, str]:
    """Pull headers off an Anthropic SDK error object, robustly. The SDK
    attaches the httpx Response under .response on APIStatusError subclasses;
    older versions used .body or .request_id. We fish for whatever is there."""
    response = getattr(exc, "response", None)
    raw = getattr(response, "headers", None) if response is not None else None
    if not raw:
        # Some versions or mocks put them on the exception directly.
        raw = getattr(exc, "headers", None)

    if not raw:
        return {}

    # httpx Headers is dict-like but case-sensitive on some platforms; normalize.
    # It might also be a list of tuples or a standard dict.
    try:
        items = raw.items() if hasattr(raw, "items") else raw
        return {str(k).lower(): str(v) for k, v in items}
    except Exception:
        return {}


def _format_reset(resets_at: str | None) -> str:
    """Render a unix-epoch (or ISO-8601) reset time as a relative string."""
    if not resets_at:
        return ""
    try:
        ts = float(resets_at)
    except ValueError:
        return resets_at  # ISO string — surface raw
    delta = max(0, int(ts - time.time()))
    if delta < 60:
        return f"in {delta}s"
    if delta < 3600:
        return f"in {delta // 60}m"
    return f"in {delta // 3600}h{(delta % 3600) // 60:02d}m"
