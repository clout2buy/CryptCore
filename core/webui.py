"""Small local WebUI server for CryptCore."""
from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
import uuid
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import (
    agent_profiles,
    app_daemon,
    autonomy,
    goals,
    learning,
    mission_router,
    passive_memory,
    project_index,
    reflection,
    session as sessions,
    settings,
    skill_forge,
    skills,
    soul,
)
from .agents import registry as agent_registry
from tools import REGISTRY


MAX_EVENTS = 500
DEFAULT_AUTONOMY_INTERVAL_SECONDS = 10 * 60


class CryptWebServer(ThreadingHTTPServer):
    def __init__(self, server_address, *, cwd: str | Path, autonomy_interval: int = 0):
        super().__init__(server_address, CryptWebHandler)
        self.cwd = Path(cwd).expanduser().resolve()
        self.events: list[dict] = []
        self.event_lock = threading.Lock()
        self.daemon = app_daemon.AppDaemon(emit=self.emit_event, cwd=str(self.cwd))
        self._autonomy_interval = max(0, int(autonomy_interval))
        self._autonomy_stop = threading.Event()
        self._autonomy_thread: threading.Thread | None = None
        if self._autonomy_interval:
            self._autonomy_thread = threading.Thread(
                target=self._autonomy_loop,
                name="crypt-webui-autonomy",
                daemon=True,
            )
            self._autonomy_thread.start()

    def emit_event(self, event: dict) -> None:
        with self.event_lock:
            event = dict(event)
            event.setdefault("seq", len(self.events) + 1)
            self.events.append(event)
            if len(self.events) > MAX_EVENTS:
                self.events[:] = self.events[-MAX_EVENTS:]

    def events_since(self, seq: int) -> list[dict]:
        with self.event_lock:
            return [event for event in self.events if int(event.get("seq") or 0) > seq]

    def server_close(self) -> None:
        self._autonomy_stop.set()
        super().server_close()

    def _autonomy_loop(self) -> None:
        if self._autonomy_stop.wait(5):
            return
        while not self._autonomy_stop.is_set():
            try:
                if not self.daemon.snapshot().get("activeTask"):
                    cycle = autonomy.run_cycle(self.cwd, max_reflections=3)
                    note = "; ".join(cycle.notes) or f"{cycle.reflected} reflection(s)"
                    self.emit_event({"event": "autonomyQuiet", "cycleId": cycle.cycle_id, "text": note})
            except Exception as exc:
                self.emit_event({"event": "autonomyError", "error": f"{type(exc).__name__}: {exc}"})
            self._autonomy_stop.wait(self._autonomy_interval)


class CryptWebHandler(BaseHTTPRequestHandler):
    server: CryptWebServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/":
            self._send_static("index.html")
            return
        if path in {"/app.js", "/styles.css"}:
            self._send_static(path.lstrip("/"))
            return
        if path == "/api/snapshot":
            self._json(self._snapshot())
            return
        if path == "/api/events":
            since = _int(query.get("since", ["0"])[0], 0)
            self._json({"events": self.server.events_since(since)})
            return
        if path == "/api/lessons":
            q = query.get("q", [""])[0]
            lessons = learning.search_lessons(self.server.cwd, q, limit=20) if q else learning.list_lessons(self.server.cwd)
            self._json({"lessons": [asdict(lesson) for lesson in lessons]})
            return
        if path == "/api/episodes":
            q = query.get("q", [""])[0]
            episodes = (
                learning.search_episodes(self.server.cwd, q, limit=20)
                if q
                else learning.list_episodes(self.server.cwd, limit=20)
            )
            self._json({"episodes": [asdict(episode) for episode in episodes]})
            return
        if path == "/api/reflections":
            self._json({"reflections": [asdict(item) for item in reflection.list_reflections(self.server.cwd, limit=20)]})
            return
        if path == "/api/autonomy":
            self._json({"cycles": [asdict(item) for item in autonomy.list_cycles(self.server.cwd, limit=20)]})
            return
        if path == "/api/goals":
            self._json({"goals": [asdict(goal) for goal in goals.list_goals(self.server.cwd, include_all=True)]})
            return
        if path == "/api/agents":
            self._json({"agents": [profile.to_dict() for profile in agent_profiles.list_profiles(self.server.cwd)]})
            return
        self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlsplit(self.path).path
        body = self._read_json()
        if path == "/api/prompt":
            text = str(body.get("text") or "").strip()
            if not text:
                self._error(HTTPStatus.BAD_REQUEST, "prompt is empty")
                return
            try:
                memory_result = passive_memory.observe(self.server.cwd, text)
            except Exception as exc:
                self.server.emit_event({"event": "memoryError", "error": f"{type(exc).__name__}: {exc}"})
            else:
                if memory_result.learned:
                    self.server.emit_event(
                        {
                            "event": "memoryLearned",
                            "text": memory_result.text,
                            "lessonId": memory_result.lesson_id,
                            "tags": list(memory_result.tags),
                            "soulChanged": memory_result.soul_changed,
                        }
                    )
            try:
                mission_result = mission_router.observe(self.server.cwd, text)
            except Exception as exc:
                mission_result = mission_router.MissionDecision(False)
                self.server.emit_event({"event": "missionError", "error": f"{type(exc).__name__}: {exc}"})
            else:
                if mission_result.created and mission_result.goal:
                    self.server.emit_event(
                        {
                            "event": "missionCreated",
                            "goal": asdict(mission_result.goal),
                            "text": mission_result.goal.title,
                            "reason": mission_result.reason,
                        }
                    )
            intents = _intent_hints(body.get("intents"))
            profile = agent_profiles.get_profile(self.server.cwd, str(body.get("agentId") or ""))
            prompt_text = _prompt_with_context(text, intents, profile, mission_result)
            request_id = str(body.get("id") or f"web-{uuid.uuid4().hex[:10]}")
            self.server.daemon.handle_command(
                {
                    "type": "sendPrompt",
                    "id": request_id,
                    "text": prompt_text,
                    "route": str(body.get("route") or ""),
                    "sessionKey": str(body.get("sessionKey") or "web"),
                }
            )
            self._json({"id": request_id})
            return
        if path == "/api/engine":
            provider = str(body.get("provider") or "").strip()
            model = str(body.get("model") or "").strip()
            request_id = str(body.get("id") or f"engine-{uuid.uuid4().hex[:10]}")
            self.server.daemon.handle_command(
                {"type": "setProviderModel", "id": request_id, "provider": provider, "model": model}
            )
            self._json({"id": request_id})
            return
        if path == "/api/route":
            role = str(body.get("role") or "").strip()
            provider = str(body.get("provider") or "").strip()
            model = str(body.get("model") or "").strip()
            request_id = str(body.get("id") or f"route-{uuid.uuid4().hex[:10]}")
            self.server.daemon.handle_command(
                {"type": "setRoute", "id": request_id, "role": role, "provider": provider, "model": model}
            )
            self._json({"id": request_id})
            return
        if path == "/api/agents":
            profile = agent_profiles.create_profile(
                self.server.cwd,
                name=str(body.get("name") or ""),
                purpose=str(body.get("purpose") or ""),
                agent_type=str(body.get("agentType") or ""),
                provider=str(body.get("provider") or ""),
                model=str(body.get("model") or ""),
            )
            if profile.provider and profile.model:
                self.server.daemon.handle_command(
                    {
                        "type": "setRoute",
                        "id": f"agent-route-{profile.id}",
                        "role": profile.route_role,
                        "provider": profile.provider,
                        "model": profile.model,
                    }
                )
            self._json({"agent": profile.to_dict()})
            return
        if path == "/api/command":
            command = str(body.get("command") or "").strip()
            request_id = str(body.get("id") or f"cmd-{uuid.uuid4().hex[:10]}")
            self.server.daemon.handle_command({"type": "runCommand", "id": request_id, "command": command})
            self._json({"id": request_id})
            return
        if path == "/api/approval":
            self.server.daemon.handle_command(
                {
                    "type": "approvalResponse",
                    "approvalId": str(body.get("approvalId") or ""),
                    "approved": bool(body.get("approved")),
                    "feedback": str(body.get("feedback") or ""),
                }
            )
            self._json({"ok": True})
            return
        if path == "/api/lessons":
            lesson = learning.add_lesson(
                str(body.get("text") or ""),
                cwd=self.server.cwd,
                scope=str(body.get("scope") or "project"),
                tags=[str(tag) for tag in body.get("tags", [])] if isinstance(body.get("tags"), list) else ["webui"],
                source="webui",
            )
            self._json({"lesson": asdict(lesson)})
            return
        if path == "/api/goals":
            goal = goals.add_goal(
                str(body.get("title") or ""),
                description=str(body.get("description") or ""),
                workspace=self.server.cwd,
                success_metric=str(body.get("successMetric") or ""),
                cadence=str(body.get("cadence") or ""),
                priority=_int(body.get("priority"), 3),
                tags=["webui"],
            )
            self._json({"goal": asdict(goal)})
            return
        if path == "/api/reflect":
            created = reflection.reflect_recent(self.server.cwd, limit=_int(body.get("limit"), 5))
            self._json({"reflections": [asdict(item) for item in created]})
            return
        if path == "/api/autonomy":
            cycle = autonomy.run_cycle(
                self.server.cwd,
                force_forge=bool(body.get("forceForge")),
                max_reflections=_int(body.get("limit"), 5),
            )
            self._json({"cycle": asdict(cycle)})
            return
        if path == "/api/forge":
            result = skill_forge.forge_skill(
                self.server.cwd,
                topic=str(body.get("topic") or ""),
                name=str(body.get("name") or ""),
                min_lessons=_int(body.get("minLessons"), 2),
            )
            self._json(
                {
                    "path": str(result.path),
                    "skillName": result.skill_name,
                    "lessonCount": result.lesson_count,
                    "created": result.created,
                }
            )
            return
        self._error(HTTPStatus.NOT_FOUND, "not found")

    def log_message(self, fmt: str, *args) -> None:
        return

    def _snapshot(self) -> dict:
        snapshot = self.server.daemon.snapshot()
        snapshot["webui"] = {
            "host": self.server.server_address[0],
            "port": self.server.server_address[1],
            "url": f"http://{self.server.server_address[0]}:{self.server.server_address[1]}/",
        }
        snapshot["project"] = asdict(project_index.get(self.server.cwd))
        snapshot["goals"] = [asdict(goal) for goal in goals.list_goals(self.server.cwd, include_all=True)[:20]]
        snapshot["lessonsPreview"] = [asdict(lesson) for lesson in learning.list_lessons(self.server.cwd)[:8]]
        snapshot["reflections"] = [asdict(item) for item in reflection.list_reflections(self.server.cwd, limit=5)]
        snapshot["autonomy"] = [asdict(item) for item in autonomy.list_cycles(self.server.cwd, limit=5)]
        soul_path = soul.ensure_soul()
        soul_update = soul.evolve(self.server.cwd)
        snapshot["soul"] = {
            "active": soul_path.exists(),
            "path": str(soul_path),
            "preferenceCount": soul_update.preference_count,
        }
        snapshot["sessionsPreview"] = [_session_preview(item) for item in sessions.list_sessions(self.server.cwd)[:12]]
        snapshot["agentProfiles"] = [profile.to_dict() for profile in agent_profiles.list_profiles(self.server.cwd)]
        snapshot["agentDefinitions"] = _agent_definition_previews()
        snapshot["skillsPreview"] = [skill.as_dict() for skill in skills.discover(self.server.cwd, include_disabled=True)[:40]]
        snapshot["toolsPreview"] = _tool_previews()
        snapshot["filesPreview"] = _workspace_files(self.server.cwd)
        snapshot["coreFeatures"] = core_features(self.server.cwd, snapshot)
        return snapshot

    def _send_static(self, name: str) -> None:
        try:
            data = resources.files("core.webui_static").joinpath(name).read_bytes()
        except (FileNotFoundError, ModuleNotFoundError):
            self._error(HTTPStatus.NOT_FOUND, "asset not found")
            return
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = _int(self.headers.get("Content-Length"), 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _json(self, data: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status=status)


def make_server(host: str, port: int, *, cwd: str | Path, autonomy_interval: int = 0) -> CryptWebServer:
    return CryptWebServer((host, port), cwd=cwd, autonomy_interval=autonomy_interval)


def core_features(cwd: str | Path, snapshot: dict) -> list[dict]:
    root = Path(cwd).expanduser().resolve()
    saved_sessions = sessions.list_sessions(root)[:5]
    discovered_skills = skills.discover(root)
    tool_schemas = REGISTRY.schemas()
    saved = settings.load_config()
    provider_rows = snapshot.get("providers", [])
    ready_providers = [row for row in provider_rows if row.get("status") == "ready"]
    goals_with_cadence = [goal for goal in goals.list_goals(root, include_all=True) if goal.cadence]
    lessons = learning.list_lessons(root)
    soul_path = soul.ensure_soul()
    routes = snapshot.get("routes", [])
    active_routes = [route for route in routes if route.get("status") == "active"]
    office_tools = [schema for schema in tool_schemas if _looks_office_tool(str(schema.get("name") or ""))]
    gateway_url = str((snapshot.get("webui") or {}).get("url") or "local")
    project = snapshot.get("project") if isinstance(snapshot.get("project"), dict) else {}
    languages = project.get("languages") if isinstance(project.get("languages"), list) else []
    frameworks = project.get("frameworks") if isinstance(project.get("frameworks"), list) else []
    git_branch = str(project.get("git_branch") or "not a git repo")
    active_goals = goals.list_goals(root)
    custom_agents = agent_profiles.list_profiles(root)
    return [
        {
            "id": "chat",
            "label": "Chat",
            "value": "live",
            "status": "primary",
            "detail": "One natural conversation surface routes work automatically.",
        },
        {
            "id": "studio",
            "label": "Studio",
            "value": root.name,
            "status": _first_nonempty([str(item) for item in languages[:2]], "workspace"),
            "detail": _first_nonempty([str(item) for item in frameworks[:3]], "Ask Crypt to inspect, build, or refactor here."),
        },
        {
            "id": "preview",
            "label": "Preview",
            "value": "local",
            "status": "browser",
            "detail": "Ask Crypt to open or verify localhost apps, screenshots, and rendered UI.",
        },
        {
            "id": "plan",
            "label": "Plan",
            "value": len(active_goals),
            "status": "goals",
            "detail": _first_nonempty(
                [goal.title for goal in active_goals[:2]],
                "Crypt auto-creates missions from chat when work needs follow-through.",
            ),
        },
        {
            "id": "sessions",
            "label": "Sessions",
            "value": len(saved_sessions),
            "status": "saved",
            "detail": _first_nonempty([item.title for item in saved_sessions], "No saved sessions yet."),
        },
        {
            "id": "profiles",
            "label": "Profiles",
            "value": "default",
            "status": "active",
            "detail": "Workspace-scoped memory, skills, config, and session state.",
        },
        {
            "id": "agents",
            "label": "Agents",
            "value": len(custom_agents),
            "status": "delegation",
            "detail": _first_nonempty([profile.name for profile in custom_agents[:3]], "Create a specialist once, then let Crypt reuse it."),
        },
        {
            "id": "office",
            "label": "Office",
            "value": "ready" if office_tools else "chat",
            "status": "docs/sheets/slides",
            "detail": "Ask in chat for docs, spreadsheets, decks, PDFs, or business ops artifacts.",
        },
        {
            "id": "models",
            "label": "Models",
            "value": str(snapshot.get("model") or "default"),
            "status": str(snapshot.get("provider") or "provider"),
            "detail": f"{len(active_routes)} active route(s) available behind chat.",
        },
        {
            "id": "providers",
            "label": "Providers",
            "value": len(ready_providers),
            "status": "ready",
            "detail": _first_nonempty([str(row.get("label") or row.get("id")) for row in ready_providers], "No ready providers."),
        },
        {
            "id": "skills",
            "label": "Skills",
            "value": len(discovered_skills),
            "status": "learnable",
            "detail": _first_nonempty([skill.name for skill in discovered_skills[:3]], "No skills discovered yet."),
        },
        {
            "id": "persona",
            "label": "Persona",
            "value": "soul",
            "status": "evolving",
            "detail": str(soul_path),
        },
        {
            "id": "memory",
            "label": "Memory",
            "value": len(lessons),
            "status": "lessons",
            "detail": _first_nonempty([lesson.text for lesson in lessons[:2]], "No durable lessons yet."),
        },
        {
            "id": "tools",
            "label": "Tools",
            "value": len(tool_schemas),
            "status": "armed",
            "detail": _first_nonempty([str(schema.get("name") or "") for schema in tool_schemas[:4]], "No tools loaded."),
        },
        {
            "id": "github",
            "label": "GitHub",
            "value": git_branch,
            "status": "repo",
            "detail": "Ask Crypt to review diffs, push branches, open PRs, or fix CI.",
        },
        {
            "id": "schedules",
            "label": "Schedules",
            "value": len(goals_with_cadence),
            "status": "cadence",
            "detail": _first_nonempty([goal.title for goal in goals_with_cadence[:2]], "Ask Crypt to watch, remind, monitor, or review."),
        },
        {
            "id": "gateway",
            "label": "Gateway",
            "value": "local",
            "status": "webui",
            "detail": gateway_url,
        },
        {
            "id": "settings",
            "label": "Settings",
            "value": str(snapshot.get("approval") or "approval"),
            "status": str(snapshot.get("thinkingMode") or "thinking"),
            "detail": f"Workspace: {saved.get('workspace') or root}",
        },
    ]


def run(*, host: str, port: int, cwd: str | Path, open_browser: bool = False) -> int:
    server = make_server(host, port, cwd=cwd, autonomy_interval=_autonomy_interval())
    url = f"http://{server.server_address[0]}:{server.server_address[1]}"
    print(f"Crypt WebUI: {url}")
    print(f"Workspace: {Path(cwd).expanduser().resolve()}")
    if open_browser:
        threading.Thread(target=lambda: _open_later(url), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


def _open_later(url: str) -> None:
    time.sleep(0.3)
    webbrowser.open(url)


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _autonomy_interval() -> int:
    raw = os.getenv("CRYPT_WEBUI_AUTONOMY_INTERVAL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_AUTONOMY_INTERVAL_SECONDS
    return max(0, _int(raw, DEFAULT_AUTONOMY_INTERVAL_SECONDS))


def _first_nonempty(values: list[str], empty: str) -> str:
    clean = [str(value).strip() for value in values if str(value).strip()]
    return ", ".join(clean[:3]) if clean else empty


def _looks_office_tool(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("doc", "sheet", "slide", "ppt", "pdf", "office"))


def _agent_definition_previews() -> list[dict]:
    out = []
    for definition in agent_registry.list_agents():
        out.append(
            {
                "name": definition.name,
                "label": definition.ui_label,
                "description": definition.description,
                "defaultMode": definition.default_mode,
                "readOnly": definition.read_only,
            }
        )
    return out


def _tool_previews(limit: int = 60) -> list[dict]:
    out = []
    for schema in REGISTRY.schemas()[:limit]:
        name = str(schema.get("name") or "")
        desc = str(schema.get("description") or "")
        out.append({"name": name, "description": desc})
    return out


def _session_preview(info) -> dict:
    data = asdict(info)
    data["path"] = str(data.get("path") or "")
    data["cwd"] = str(data.get("cwd") or "")
    return data


def _workspace_files(cwd: str | Path, *, limit: int = 80) -> list[dict]:
    root = Path(cwd).expanduser().resolve()
    out: list[dict] = []
    try:
        entries = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError:
        return out
    for item in entries:
        if item.name.startswith(".") and item.name not in {".github", ".crypt", ".agents"}:
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        out.append(
            {
                "name": item.name,
                "path": str(item),
                "kind": "dir" if item.is_dir() else "file",
                "size": stat.st_size if item.is_file() else 0,
                "updatedAt": int(stat.st_mtime),
            }
        )
        if len(out) >= limit:
            break
    return out


def _intent_hints(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    allowed = {"web", "files", "build", "auto"}
    out: list[str] = []
    for item in value:
        clean = str(item or "").strip().lower()
        if clean in allowed and clean not in out:
            out.append(clean)
    return out


def _prompt_with_context(
    text: str,
    intents: list[str],
    profile: agent_profiles.AgentProfile | None = None,
    mission: mission_router.MissionDecision | None = None,
) -> str:
    hints: list[str] = []
    hint_map = {
        "web": "use web research if it helps",
        "files": "inspect local files if needed",
        "build": "prefer implementing the next concrete change",
        "auto": "handle safe follow-up steps without extra orchestration",
    }
    hints.extend(hint_map[item] for item in intents if item in hint_map)
    if profile:
        hints.append(
            (
                f"selected saved agent '{profile.name}' "
                f"({profile.agent_type}, route {profile.route_role}, {profile.provider}/{profile.model}); "
                "delegate with the matching built-in agent type when that helps"
            )
        )
    if mission and mission.prompt_hint:
        hints.append(mission.prompt_hint)
    if not hints:
        return text
    return f"{text}\n\n[Crypt runtime hints: {'; '.join(hints)}]"
