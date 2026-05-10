"""JSONL bridge for the Electron desktop client.

The daemon is intentionally thin: it does not own provider logic, tool logic,
sessions, approvals, or routing. It delegates turns into ``core.loop.run_prompt``
so the terminal and Electron clients stay skins over the same Crypt engine.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from . import auth, doctor, loop, redact, runtime, session as sessions, settings
from tools import REGISTRY


Emit = Callable[[dict], None]
ROUTE_ROLES = ("planner", "builder", "reviewer", "fast", "fallback")


def _stdin_lines():
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    try:
        fd = stream.fileno()
    except (AttributeError, OSError):
        yield from sys.stdin
        return

    pending = b""
    while True:
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            yield line.decode("utf-8", errors="replace")
    if pending:
        yield pending.decode("utf-8", errors="replace")


class AppDaemon:
    def __init__(self, *, emit: Emit | None = None, cwd: str | None = None) -> None:
        self._emit = emit or self._stdout_emit
        self._write_lock = threading.Lock()
        self._task_lock = threading.Lock()
        self._active_task: str | None = None
        self._cwd = Path(cwd or settings.resolve_workspace(None, settings.load_config())).resolve()
        self._sessions: dict[str, sessions.Session] = {}
        self._active_session_key = "default"
        self._task_session_keys: dict[str, str] = {}
        self._approval_lock = threading.Lock()
        self._approval_waiters: dict[str, dict] = {}

    def run_forever(self) -> int:
        self.emit("ready", snapshot=self.snapshot())
        for raw in _stdin_lines():
            line = raw.strip()
            if not line:
                continue
            try:
                command = json.loads(line)
                if not isinstance(command, dict):
                    raise ValueError("command must be a JSON object")
                self.handle_command(command)
            except Exception as exc:
                self.emit("error", error=f"{type(exc).__name__}: {exc}")
        return 0

    def handle_command(self, command: dict) -> None:
        ctype = str(command.get("type") or "")
        cid = str(command.get("id") or "")
        if ctype in {"hello", "snapshot"}:
            self.emit("snapshot", id=cid, snapshot=self.snapshot())
            return
        if ctype == "setApproval":
            mode = str(command.get("mode") or settings.load_config().get("approval") or runtime.APPROVAL_EDITS)
            runtime.set_approval_mode(mode)
            self.emit("snapshot", id=cid, snapshot=self.snapshot())
            return
        if ctype == "approvalResponse":
            self._resolve_approval(command)
            return
        if ctype == "setThinking":
            mode = str(command.get("mode") or "").strip().lower()
            if mode:
                runtime.set_thinking_mode(mode)
            else:
                runtime.set_show_thinking(bool(command.get("enabled")))
            self.emit("snapshot", id=cid, snapshot=self.snapshot())
            return
        if ctype == "setWorkspace":
            path = Path(str(command.get("path") or "")).expanduser().resolve()
            if not path.exists() or not path.is_dir():
                self.emit("error", id=cid, error=f"workspace does not exist: {path}")
                return
            self._cwd = path
            runtime.set_cwd(str(path))
            self._sessions.clear()
            self.emit("snapshot", id=cid, snapshot=self.snapshot())
            return
        if ctype == "setProviderModel":
            self._set_provider_model(command, request_id=cid)
            return
        if ctype == "setRoute":
            self._set_route(command, request_id=cid)
            return
        if ctype == "newSession":
            self._new_session(request_id=cid, session_key=_session_key(command))
            return
        if ctype == "runCommand":
            self._run_command(str(command.get("command") or ""), request_id=cid)
            return
        if ctype == "sendPrompt":
            text = str(command.get("text") or "").strip()
            if not text:
                self.emit("error", id=cid, error="prompt is empty")
                return
            if text.startswith("/"):
                self._run_command(text[1:], request_id=cid, session_key=_session_key(command))
                return
            route_role = str(command.get("route") or "").strip().lower() or None
            self._start_prompt(text, request_id=cid, route_role=route_role, session_key=_session_key(command))
            return
        self.emit("error", id=cid, error=f"unknown command: {ctype or '<missing>'}")

    def snapshot(self) -> dict:
        saved = settings.load_config()
        provider_name = settings.provider_default(saved)
        model = settings.model_default(provider_name, saved)
        cred = _credential(provider_name)
        auth_label = _auth_label(provider_name, cred)
        auth_ok = _credential_is_usable(provider_name, cred)
        return {
            "workspace": str(self._cwd),
            "provider": provider_name,
            "model": model,
            "auth": auth_label,
            "authOk": auth_ok,
            "authMessage": "" if auth_ok else _provider_missing_auth_message(provider_name),
            "approval": runtime.approval_label(),
            "approvalMode": runtime.approval_mode(),
            "showThinking": runtime.show_thinking(),
            "thinkingMode": runtime.thinking_mode(),
            "reasoningEffort": runtime.reasoning_effort() or "none",
            "tools": len(REGISTRY.schemas()),
            "sessionId": getattr(self._sessions.get(self._active_session_key), "id", None),
            "desktopSessionKey": self._active_session_key,
            "activeTask": self._active_task,
            "providers": _provider_inventory(saved),
            "routes": _routes(saved),
        }

    def emit(self, event: str, **payload) -> None:
        body = {"event": event, "ts": time.time(), **payload}
        self._emit(_redact_payload(body))

    def _stdout_emit(self, event: dict) -> None:
        with self._write_lock:
            print(json.dumps(event, ensure_ascii=False), flush=True)

    def _start_prompt(
        self,
        text: str,
        *,
        request_id: str,
        route_role: str | None = None,
        session_key: str = "default",
    ) -> None:
        with self._task_lock:
            if self._active_task:
                self.emit("error", id=request_id, error=f"task already running: {self._active_task}")
                return
            if route_role and route_role not in ROUTE_ROLES:
                self.emit("error", id=request_id, error=f"unknown route role: {route_role}")
                return
            task_id = request_id or uuid.uuid4().hex
            self._active_task = task_id
            self._active_session_key = session_key
            self._task_session_keys[task_id] = session_key
        self._run_prompt_task(task_id, text, route_role)

    def _run_prompt_task(self, task_id: str, text: str, route_role: str | None) -> None:
        session_key = self._task_session_keys.get(task_id, "default")
        self._active_session_key = session_key
        self.emit("taskStarted", id=task_id, prompt=text, routeRole=route_role, sessionKey=session_key, snapshot=self.snapshot())
        try:
            saved = settings.load_config()
            provider_name = settings.provider_default(saved)
            cred = _credential(provider_name)
            if route_role:
                route = _route_lookup(saved, route_role)
                if not route:
                    raise RuntimeError(f"route not found: {route_role}")
                provider = _provider_from_route(saved, route)
                provider_name = provider.name
            else:
                if not _credential_is_usable(provider_name, cred):
                    raise RuntimeError(_provider_missing_auth_message(provider_name))
                provider = _provider(saved, provider_name, cred)
            self.emit(
                "taskProgress",
                id=task_id,
                phase="provider",
                routeRole=route_role,
                sessionKey=session_key,
                text=f"{provider.name} / {provider.model}",
            )
            session_obj = self._sessions.get(session_key)
            if session_obj is None:
                session_obj = sessions.Session(self._cwd, provider=provider.name, model=provider.model)
                self._sessions[session_key] = session_obj
            self.emit("taskProgress", id=task_id, phase="running", routeRole=route_role, sessionKey=session_key, text="engine started")

            def emit_live(payload: dict) -> None:
                event = str(payload.get("event") or "event")
                data = {key: value for key, value in payload.items() if key != "event"}
                self.emit(event, id=task_id, routeRole=route_role, sessionKey=session_key, **data)

            def approve_tool(**approval: object) -> tuple[bool, str]:
                return self._request_approval(
                    task_id=task_id,
                    session_key=session_key,
                    **approval,
                )

            with runtime.approval_handler(approve_tool):
                result = loop.run_prompt(
                    provider,
                    text,
                    cwd=str(self._cwd),
                    session_obj=session_obj,
                    approval_mode=runtime.approval_mode(),
                    show_thinking=runtime.show_thinking(),
                    render=False,
                    subagent_provider_factory=lambda agent_type: _provider_for_route(saved, agent_type, fallback=provider),
                    event_sink=emit_live,
                )
            self.emit(
                "taskFinished",
                id=task_id,
                text=result.final_text,
                routeRole=route_role,
                sessionKey=session_key,
                currentTokens=result.current_tokens,
                sessionTokens=result.session_tokens,
                snapshot=self.snapshot(),
            )
        except Exception as exc:
            self.emit(
                "taskFailed",
                id=task_id,
                routeRole=route_role,
                sessionKey=session_key,
                error=f"{type(exc).__name__}: {exc}",
                snapshot=self.snapshot(),
            )
        finally:
            with self._task_lock:
                self._active_task = None
                self._task_session_keys.pop(task_id, None)
            self.emit("snapshot", snapshot=self.snapshot())

    def _request_approval(
        self,
        *,
        task_id: str,
        session_key: str,
        question: object,
        tool_name: object,
        args: object,
        danger: object = False,
        reason: object = None,
        summary: object = "",
    ) -> tuple[bool, str]:
        approval_id = f"approval-{uuid.uuid4().hex}"
        done = threading.Event()
        record = {"done": done, "approved": False, "feedback": ""}
        with self._approval_lock:
            self._approval_waiters[approval_id] = record
        self.emit(
            "approvalRequested",
            id=task_id,
            approvalId=approval_id,
            sessionKey=session_key,
            question=str(question or "run this?"),
            tool=str(tool_name or ""),
            args=args if isinstance(args, dict) else None,
            danger=bool(danger),
            reason=str(reason or ""),
            text=str(summary or ""),
        )
        done.wait()
        with self._approval_lock:
            self._approval_waiters.pop(approval_id, None)
            approved = bool(record.get("approved"))
            feedback = str(record.get("feedback") or "")
        self.emit(
            "approvalResolved",
            id=task_id,
            approvalId=approval_id,
            sessionKey=session_key,
            approved=approved,
            text="approved" if approved else "denied",
        )
        return approved, feedback

    def _resolve_approval(self, command: dict) -> None:
        approval_id = str(command.get("approvalId") or "")
        with self._approval_lock:
            record = self._approval_waiters.get(approval_id)
            if record is None:
                self.emit("error", id=str(command.get("id") or ""), error=f"unknown approval request: {approval_id}")
                return
            record["approved"] = bool(command.get("approved"))
            record["feedback"] = str(command.get("feedback") or "")
            done = record["done"]
        done.set()

    def _set_provider_model(self, command: dict, *, request_id: str) -> None:
        if self._active_task:
            self.emit("error", id=request_id, error=f"task already running: {self._active_task}")
            return
        provider = str(command.get("provider") or "").strip()
        if provider not in settings.PROVIDERS:
            self.emit("error", id=request_id, error=f"unknown provider: {provider or '<missing>'}")
            return
        model = str(command.get("model") or settings.model_default(provider, settings.load_config())).strip()
        if not model:
            self.emit("error", id=request_id, error="model is empty")
            return
        _save_provider_model(settings.load_config(), provider, model, self._cwd)
        self._sessions.clear()
        self.emit(
            "commandResult",
            id=request_id,
            command="setProviderModel",
            text=f"Active engine set to {provider} / {model}",
        )
        self.emit("snapshot", id=request_id, snapshot=self.snapshot())

    def _set_route(self, command: dict, *, request_id: str) -> None:
        role = str(command.get("role") or "").strip().lower()
        provider = str(command.get("provider") or "").strip()
        model = str(command.get("model") or "").strip()
        if role not in ROUTE_ROLES:
            self.emit("error", id=request_id, error=f"unknown route role: {role or '<missing>'}")
            return
        if provider not in settings.PROVIDERS:
            self.emit("error", id=request_id, error=f"unknown provider: {provider or '<missing>'}")
            return
        if not model:
            model = settings.model_default(provider, settings.load_config())
        saved = settings.load_config()
        routes = [dict(item) for item in _routes(saved)]
        for item in routes:
            if item["role"] == role:
                item.update({"provider": provider, "model": model, "status": "active"})
                break
        else:
            routes.append({"role": role, "provider": provider, "model": model, "status": "active"})
        settings.update_config(desktop_routes=routes)
        self.emit("commandResult", id=request_id, command="setRoute", text=f"{role} route set to {provider} / {model}")
        self.emit("snapshot", id=request_id, snapshot=self.snapshot())

    def _new_session(self, *, request_id: str, session_key: str = "default") -> None:
        if self._active_task:
            self.emit("error", id=request_id, error=f"task already running: {self._active_task}")
            return
        self._active_session_key = session_key
        self._sessions.pop(session_key, None)
        self.emit("sessionReset", id=request_id, sessionKey=session_key, text="Session cleared")
        self.emit("snapshot", id=request_id, snapshot=self.snapshot())

    def _run_command(self, command: str, *, request_id: str, session_key: str = "default") -> None:
        parts = command.strip().split()
        name = (parts[0].lower() if parts else "status").lstrip("/")
        args = parts[1:]
        if name in {"status", "snapshot"}:
            self.emit("commandResult", id=request_id, command=name, text=_status_text(self.snapshot()))
            self.emit("snapshot", id=request_id, snapshot=self.snapshot())
            return
        if name == "doctor":
            self.emit("commandResult", id=request_id, command=name, text=doctor.run_doctor(self._cwd))
            self.emit("snapshot", id=request_id, snapshot=self.snapshot())
            return
        if name in {"clear", "new", "new-session"}:
            self._new_session(request_id=request_id, session_key=session_key)
            self.emit("commandResult", id=request_id, command=name, text="Session cleared")
            return
        if name in {"yolo", "auto"}:
            mode = runtime.APPROVAL_ALL
            if args and args[0].lower() in {"work", "edits", "auto-work"}:
                mode = runtime.APPROVAL_EDITS
            if args and args[0].lower() in {"manual", "safe", "off", "normal"}:
                mode = runtime.APPROVAL_NORMAL
            runtime.set_approval_mode(mode)
            self.emit("commandResult", id=request_id, command=name, text=f"Approval set to {runtime.approval_label()}")
            self.emit("snapshot", id=request_id, snapshot=self.snapshot())
            return
        if name in {"safe", "manual"}:
            runtime.set_approval_mode(runtime.APPROVAL_NORMAL)
            self.emit("commandResult", id=request_id, command=name, text=f"Approval set to {runtime.approval_label()}")
            self.emit("snapshot", id=request_id, snapshot=self.snapshot())
            return
        if name in {"thinking", "think"}:
            if args:
                mode = runtime.set_thinking_mode(args[0])
            else:
                mode = runtime.set_thinking_mode(
                    runtime.THINKING_FAST if runtime.show_thinking() else runtime.THINKING_THINK
                )
            self.emit("commandResult", id=request_id, command=name, text=f"Thinking mode set to {mode}")
            self.emit("snapshot", id=request_id, snapshot=self.snapshot())
            return
        if name in {"help", "commands"}:
            self.emit("commandResult", id=request_id, command=name, text=_help_text())
            self.emit("snapshot", id=request_id, snapshot=self.snapshot())
            return
        self.emit("error", id=request_id, error=f"unknown command: /{name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crypt app-daemon")
    parser.add_argument("--cwd", help="workspace root")
    args = parser.parse_args(argv)
    return AppDaemon(cwd=args.cwd).run_forever()


def _args(model: str | None = None) -> SimpleNamespace:
    thinking_mode = runtime.thinking_mode()
    return SimpleNamespace(
        model=model,
        max_tokens=settings.ANTHROPIC_ESCALATED_MAX_TOKENS if thinking_mode == runtime.THINKING_ULTRA else None,
        thinking_budget=runtime.thinking_budget(),
        no_thinking=thinking_mode == runtime.THINKING_FAST,
        show_thinking=runtime.show_thinking(),
        reasoning_effort=runtime.reasoning_effort(),
        thinking_mode=thinking_mode,
        ollama_host=None,
    )


def _credential(provider_name: str) -> auth.Credential | None:
    import main as cli

    return cli._credential(provider_name)


def _session_key(command: dict) -> str:
    value = str(command.get("sessionKey") or command.get("session") or "default").strip()
    return value or "default"


def _credential_is_usable(provider_name: str, cred: auth.Credential | None) -> bool:
    import main as cli

    return cli._credential_is_usable(provider_name, cred)


def _provider_missing_auth_message(provider_name: str) -> str:
    import main as cli

    return cli._provider_missing_auth_message(provider_name)


def _provider(saved: dict, provider_name: str, cred: auth.Credential | None, model_override: str | None = None):
    import main as cli

    return cli._provider(_args(model_override), saved, provider_name, cred, model_override=model_override)


def _provider_for_route(saved: dict, agent_type: str, *, fallback):
    role = _route_role_for_agent(agent_type)
    route = _route_lookup(saved, role)
    if not route:
        return fallback
    try:
        return _provider_from_route(saved, route)
    except Exception:
        fallback_route = _route_lookup(saved, "fallback")
        if fallback_route and fallback_route != route:
            return _provider_from_route(saved, fallback_route)
        raise


def _provider_from_route(saved: dict, route: dict):
    provider_name = str(route.get("provider") or "")
    model = str(route.get("model") or "")
    if provider_name not in settings.PROVIDERS:
        raise RuntimeError(f"route {route.get('role')} has unknown provider: {provider_name}")
    cred = _credential(provider_name)
    if not _credential_is_usable(provider_name, cred):
        raise RuntimeError(f"route {route.get('role')} cannot run: {_provider_missing_auth_message(provider_name)}")
    route_saved = dict(saved)
    if provider_name == settings.PROVIDER_OLLAMA and model:
        route_saved["ollama_host"] = _desktop_ollama_host(model, saved)
    return _provider(route_saved, provider_name, cred, model_override=model or None)


def _route_lookup(saved: dict, role: str) -> dict | None:
    for route in _routes(saved):
        if route["role"] == role:
            return route
    return None


def _route_role_for_agent(agent_type: str) -> str:
    if agent_type == "worker":
        return "builder"
    if agent_type in {"verifier", "ui_reviewer", "release_reviewer"}:
        return "reviewer"
    if agent_type in {"explorer", "planner"}:
        return "planner"
    return "fallback"


def _save_provider_model(saved: dict, provider_name: str, model: str, cwd: Path) -> dict:
    values: dict[str, object] = {"provider": provider_name, "workspace": str(cwd)}
    if provider_name == settings.PROVIDER_ANTHROPIC:
        values["anthropic_model"] = model
    elif provider_name == settings.PROVIDER_OPENAI:
        values["openai_model"] = model
    elif provider_name == settings.PROVIDER_OPENAI_CODEX:
        values["openai_codex_model"] = model
    elif provider_name == settings.PROVIDER_GEMINI:
        values["gemini_model"] = model
        project_id = settings.gemini_project_id(saved)
        if project_id:
            values["gemini_project_id"] = project_id
        location = settings.gemini_vertex_location(saved)
        if location:
            values["gemini_location"] = location
    else:
        values["ollama_model"] = model
        values["ollama_host"] = _desktop_ollama_host(model, saved)
    return settings.update_config(**values)


def _desktop_ollama_host(model: str, saved: dict) -> str:
    if settings.is_ollama_cloud_model(model):
        return "https://ollama.com"
    saved_host = str(saved.get("ollama_host") or "")
    if saved_host and not settings.is_ollama_cloud_host(saved_host):
        return settings.client_host(saved_host)
    return settings.OLLAMA_HOST


def _auth_label(provider_name: str, cred: auth.Credential | None) -> str:
    if provider_name == settings.PROVIDER_OPENAI:
        return "OPENAI_API_KEY" if os.getenv("OPENAI_API_KEY") else "missing OPENAI_API_KEY"
    if provider_name == settings.PROVIDER_ANTHROPIC:
        return cred.kind if cred else "missing Anthropic auth"
    if provider_name == settings.PROVIDER_OPENAI_CODEX:
        return "ChatGPT OAuth" if cred else "missing ChatGPT OAuth"
    if provider_name == settings.PROVIDER_GEMINI:
        if os.getenv("GEMINI_API_KEY"):
            return "GEMINI_API_KEY"
        return "Google OAuth" if cred else "missing Gemini auth"
    return "local Ollama" if provider_name == settings.PROVIDER_OLLAMA else "unknown"


def _provider_inventory(saved: dict) -> list[dict]:
    return [
        _provider_row(
            settings.PROVIDER_ANTHROPIC,
            "Anthropic OAuth",
            settings.ANTHROPIC_MODELS,
            status="ready",
        ),
        _provider_row(
            settings.PROVIDER_OPENAI,
            "OpenAI compatible",
            settings.OPENAI_MODELS,
            status="ready",
        ),
        _provider_row(
            settings.PROVIDER_OPENAI_CODEX,
            "ChatGPT / Codex OAuth",
            settings.OPENAI_CODEX_MODELS,
            status="ready",
        ),
        _provider_row(
            settings.PROVIDER_GEMINI,
            "Gemini OAuth/API key",
            settings.GEMINI_MODELS,
            status="construction",
            note="OAuth and streaming are wired; keep this provider under verification.",
        ),
        _provider_row(
            settings.PROVIDER_OLLAMA,
            "Ollama local/cloud",
            settings.ollama_models_for_host(settings.ollama_host(saved=saved)),
            status="ready",
            model_groups=[
                {"id": "local", "label": "Local", "models": list(settings.OLLAMA_LOCAL_MODELS)},
                {"id": "cloud", "label": "Cloud", "models": list(settings.OLLAMA_CLOUD_MODELS)},
            ],
        ),
    ]


def _provider_row(
    provider_id: str,
    label: str,
    models: tuple[str, ...] | list[str],
    *,
    status: str,
    note: str = "",
    model_groups: list[dict] | None = None,
) -> dict:
    return {
        "id": provider_id,
        "label": label,
        "models": list(models),
        "modelGroups": model_groups or [{"id": "default", "label": "Models", "models": list(models)}],
        "status": status,
        "note": note,
    }


def _routes(saved: dict) -> list[dict]:
    configured = saved.get("desktop_routes")
    if isinstance(configured, list):
        routes: list[dict] = []
        for item in configured:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").lower()
            provider = str(item.get("provider") or "")
            if role not in ROUTE_ROLES or provider not in settings.PROVIDERS:
                continue
            model = str(item.get("model") or settings.model_default(provider, saved))
            routes.append(
                {
                    "role": role,
                    "provider": provider,
                    "model": model,
                    "status": str(item.get("status") or "active"),
                }
            )
        if routes:
            existing = {item["role"] for item in routes}
            routes.extend(_default_route(saved, role) for role in ROUTE_ROLES if role not in existing)
            return routes
    return [_default_route(saved, role) for role in ROUTE_ROLES]


def _default_route(saved: dict, role: str) -> dict:
    provider = settings.provider_default(saved)
    model = settings.model_default(provider, saved)
    status = "pending" if role in {"reviewer", "fallback"} else "active"
    return {"role": role, "provider": provider, "model": model, "status": status}


def _status_text(snapshot: dict) -> str:
    lines = [
        "Crypt desktop status",
        f"workspace: {snapshot['workspace']}",
        f"engine: {snapshot['provider']} / {snapshot['model']}",
        f"auth: {snapshot['auth']}",
        f"approval: {snapshot['approval']}",
        f"thinking: {snapshot['thinkingMode']}",
        f"tools: {snapshot['tools']} armed",
    ]
    if snapshot.get("activeTask"):
        lines.append(f"active task: {snapshot['activeTask']}")
    if snapshot.get("sessionId"):
        lines.append(f"session: {snapshot['sessionId']}")
    return "\n".join(lines)


def _help_text() -> str:
    return "\n".join(
        [
            "Crypt desktop commands",
            "/status - print engine state",
            "/doctor - run local harness checks",
            "/clear - start a fresh session",
            "/yolo - auto-approve all tool work",
            "/yolo edits - auto-approve edit tools only",
            "/safe - require manual approval",
            "/thinking [fast|think|ultra] - set provider reasoning mode",
        ]
    )


def _timeline_events(messages: list[dict]) -> list[dict]:
    events: list[dict] = []
    names_by_id: dict[str, str] = {}
    args_by_id: dict[str, object] = {}
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "assistant":
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                call_id = str(block.get("id") or "")
                name = str(block.get("name") or "tool")
                names_by_id[call_id] = name
                args_by_id[call_id] = block.get("input") or {}
                events.append(
                    {
                        "event": "toolCall",
                        "tool": name,
                        "callId": call_id,
                        "args": block.get("input") or {},
                        "text": _tool_call_text(name, block.get("input") or {}),
                    }
                )
        elif role == "user":
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                call_id = str(block.get("tool_use_id") or "")
                tool_name = names_by_id.get(call_id, "tool")
                is_error = bool(block.get("is_error"))
                events.append(
                    {
                        "event": "toolResult",
                        "tool": tool_name,
                        "callId": call_id,
                        "args": args_by_id.get(call_id) if isinstance(args_by_id.get(call_id), dict) else None,
                        "ok": not is_error,
                        "text": _tool_result_text(tool_name, block.get("content"), is_error=is_error),
                    }
                )
    return events


def _tool_call_text(name: str, args: object) -> str:
    if name == "spawn_agent" and isinstance(args, dict):
        agent = args.get("agent_type") or "agent"
        desc = args.get("description") or args.get("prompt") or "subagent"
        return f"{agent}: {desc}"
    if isinstance(args, dict):
        target = args.get("path") or args.get("command") or args.get("query") or args.get("description")
        if target:
            return f"{name}: {target}"
    return name


def _tool_result_text(name: str, content: object, *, is_error: bool) -> str:
    text = str(content or "").strip()
    if not text:
        return f"{name} {'failed' if is_error else 'completed'}"
    lines = text.splitlines()
    preview = "\n".join(lines[:5])
    if len(preview) > 900:
        preview = preview[:900].rstrip() + "..."
    return preview


def _redact_payload(value):
    if isinstance(value, str):
        return redact.text(value)
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_payload(item) for key, item in value.items()}
    return value
