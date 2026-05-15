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
    artifact_studio,
    business_mission,
    clarification_policy,
    code_builder,
    context_packs,
    entities,
    goals,
    integrations,
    intent_router,
    knowledge_graph,
    learning,
    local_voice,
    memory_journal,
    mcp_gateway,
    mission_brain,
    mission_router,
    monitors,
    passive_memory,
    project_index,
    reflection,
    revenue,
    runtime_rebuild,
    scheduler,
    session as sessions,
    settings,
    skill_forge,
    skills,
    soul,
    upgrade_queue,
    work_threads,
    live_events,
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
        self._event_seq = 0
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
            event = live_events.normalize_event(event, strict=False)
            if "seq" in event:
                self._event_seq = max(self._event_seq, _int(event.get("seq"), self._event_seq))
            else:
                self._event_seq += 1
                event["seq"] = self._event_seq
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
        if path == "/api/work-threads":
            self._json({"threads": [asdict(thread) for thread in work_threads.list_threads(self.server.cwd, include_all=True)]})
            return
        if path == "/api/agents":
            self._json({"agents": [profile.to_dict() for profile in agent_profiles.list_profiles(self.server.cwd)]})
            return
        if path == "/api/voice":
            self._json({"voice": local_voice.status().to_dict()})
            return
        if path.startswith("/api/voice/audio/"):
            try:
                audio_path = local_voice.audio_path(path.rsplit("/", 1)[-1])
            except FileNotFoundError:
                self._error(HTTPStatus.NOT_FOUND, "voice audio not found")
                return
            data = audio_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
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
            request_id = str(body.get("id") or f"web-{uuid.uuid4().hex[:10]}")
            session_key = str(body.get("sessionKey") or "web")
            intent_decision = intent_router.route(text)
            action_decision = clarification_policy.decide(intent_decision)
            self.server.emit_event(
                {
                    "event": "intentRouted",
                    "id": request_id,
                    "sessionKey": session_key,
                    "intent": intent_decision.intent,
                    "routeRole": intent_decision.route_role,
                    "confidence": intent_decision.confidence,
                    "rationale": intent_decision.rationale,
                    "durable": intent_decision.durable,
                    "needsApproval": intent_decision.needs_approval,
                    "needsClarification": intent_decision.needs_clarification,
                    "text": intent_router.prompt_hint(intent_decision),
                }
            )
            try:
                journal_result = memory_journal.observe(self.server.cwd, text)
            except Exception as exc:
                self.server.emit_event({"event": "memoryJournalError", "error": f"{type(exc).__name__}: {exc}"})
            else:
                if journal_result.changed:
                    self.server.emit_event(
                        {
                            "event": "memoryJournalUpdated",
                            "text": journal_result.text,
                            "category": journal_result.category,
                            "promoted": journal_result.promoted,
                            "path": str(journal_result.path),
                        }
                    )
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
                feedback_result = learning.record_user_correction(self.server.cwd, text, source="webui")
            except Exception as exc:
                self.server.emit_event({"event": "outcomeLearnError", "error": f"{type(exc).__name__}: {exc}"})
            else:
                if feedback_result.get("learned"):
                    self.server.emit_event(
                        {
                            "event": "outcomeLearned",
                            "text": str(feedback_result.get("text") or "User correction captured."),
                            "lessons": [feedback_result.get("text")],
                            "episodeId": "",
                        }
                    )
            try:
                entity_result = entities.observe_text(self.server.cwd, text)
            except Exception as exc:
                self.server.emit_event({"event": "entitiesError", "error": f"{type(exc).__name__}: {exc}"})
            else:
                if entity_result.changed:
                    self.server.emit_event(
                        {
                            "event": "entitiesUpdated",
                            "text": f"{len(entity_result.records)} typed entity signal(s) captured.",
                            "count": entity_result.count,
                            "path": str(entity_result.path),
                        }
                    )
            try:
                mission_result = mission_router.observe(self.server.cwd, text, route=intent_decision)
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
                elif mission_result.duplicate and mission_result.goal:
                    self.server.emit_event(
                        {
                            "event": "missionMatched",
                            "goal": asdict(mission_result.goal),
                            "text": mission_result.goal.title,
                            "reason": mission_result.reason,
                        }
                    )
                if mission_result.goal:
                    try:
                        thread = work_threads.ensure_for_goal(mission_result.goal, prompt_text=text)
                    except Exception as exc:
                        self.server.emit_event({"event": "workThreadError", "error": f"{type(exc).__name__}: {exc}"})
                    else:
                        self.server.emit_event(
                            {
                                "event": "workThreadUpdated",
                                "thread": asdict(thread),
                                "text": thread.title,
                                "state": thread.state,
                                "nextAction": thread.next_action,
                            }
                        )
            intents = _intent_hints(body.get("intents"))
            profile = agent_profiles.get_profile(self.server.cwd, str(body.get("agentId") or ""))
            prompt_text = _prompt_with_context(
                text,
                intents,
                profile,
                mission_result,
                intent_decision,
                action_decision,
                workspace=self.server.cwd,
            )
            route_role = str(body.get("route") or "").strip() or intent_decision.route_role
            self.server.daemon.handle_command(
                {
                    "type": "sendPrompt",
                    "id": request_id,
                    "text": prompt_text,
                    "route": route_role,
                    "sessionKey": session_key,
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
        if path == "/api/voice/speak":
            try:
                result = local_voice.speak(
                    str(body.get("text") or ""),
                    voice=str(body.get("voice") or local_voice.DEFAULT_VOICE),
                    speed=float(body.get("speed") or local_voice.DEFAULT_SPEED),
                )
            except Exception as exc:
                self._error(HTTPStatus.CONFLICT, f"{type(exc).__name__}: {exc}")
                return
            self._json({"speech": result.to_dict()})
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
            thread = work_threads.ensure_for_goal(goal, prompt_text=str(body.get("description") or ""), source="webui")
            self._json({"goal": asdict(goal), "thread": asdict(thread)})
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
        snapshot["workThreads"] = [asdict(thread) for thread in work_threads.list_threads(self.server.cwd, include_all=True)[:20]]
        snapshot["memoryJournal"] = memory_journal.snapshot(self.server.cwd)
        snapshot["entitiesPreview"] = entities.snapshot(self.server.cwd)
        snapshot["knowledgeGraph"] = knowledge_graph.snapshot(self.server.cwd)
        snapshot["contextPackPreview"] = context_packs.preview(self.server.cwd)
        snapshot["selfUpgradeQueue"] = upgrade_queue.snapshot(self.server.cwd)
        snapshot["runtimeRebuild"] = runtime_rebuild.snapshot(self.server.cwd)
        snapshot["mcpGateway"] = mcp_gateway.snapshot(self.server.cwd)
        snapshot["lessonsPreview"] = [asdict(lesson) for lesson in learning.list_lessons(self.server.cwd)[:8]]
        snapshot["reflections"] = [asdict(item) for item in reflection.list_reflections(self.server.cwd, limit=5)]
        snapshot["autonomy"] = [asdict(item) for item in autonomy.list_cycles(self.server.cwd, limit=5)]
        snapshot["schedulesPreview"] = [asdict(item) for item in scheduler.list_jobs(self.server.cwd, include_all=True)[:20]]
        snapshot["monitorsPreview"] = [asdict(item) for item in monitors.list_monitors(self.server.cwd, include_all=True)[:20]]
        snapshot["revenue"] = revenue.dashboard_snapshot(self.server.cwd)
        snapshot["integrationsPreview"] = integrations.snapshot()
        soul_path = soul.ensure_soul()
        soul_update = soul.evolve(self.server.cwd)
        snapshot["soul"] = {
            "active": soul_path.exists(),
            "path": str(soul_path),
            "preferenceCount": soul_update.preference_count,
        }
        snapshot["voice"] = local_voice.status().to_dict()
        snapshot["sessionsPreview"] = [_session_preview(item) for item in sessions.list_sessions(self.server.cwd)[:12]]
        snapshot["agentProfiles"] = [profile.to_dict() for profile in agent_profiles.list_profiles(self.server.cwd)]
        snapshot["agentDefinitions"] = _agent_definition_previews()
        snapshot["skillsPreview"] = [skill.as_dict() for skill in skills.discover(self.server.cwd, include_disabled=True)[:40]]
        snapshot["toolsPreview"] = _tool_previews()
        snapshot["filesPreview"] = _workspace_files(self.server.cwd)
        studio = artifact_studio.snapshot(self.server.cwd)
        snapshot["artifactsPreview"] = studio["artifacts"]
        snapshot["artifactGroups"] = studio["groups"]
        snapshot["artifactSummary"] = studio["summary"]
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
    thread_status = work_threads.status(root)
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
            "value": thread_status.active + thread_status.blocked + thread_status.waiting,
            "status": "threads",
            "detail": _first_nonempty(
                [thread.title for thread in work_threads.list_threads(root)[:2]],
                _first_nonempty(
                    [goal.title for goal in active_goals[:2]],
                    "Crypt auto-creates missions and work threads from chat.",
                ),
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
            "value": _display_model_label(str(snapshot.get("model") or "default")),
            "status": _display_provider_label(str(snapshot.get("provider") or "provider"), snapshot),
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
        meta = schema.get("x_crypt") if isinstance(schema.get("x_crypt"), dict) else {}
        out.append(
            {
                "name": name,
                "description": desc,
                "capability": str(meta.get("capability") or ""),
                "risk": str(meta.get("risk") or ""),
                "permissionNeeds": list(meta.get("permissionNeeds") or []),
                "recoveryHints": list(meta.get("recoveryHints") or []),
            }
        )
    return out


def _display_model_label(model: str) -> str:
    labels = {
        "crypt-pro": "ChatGPT 5 Codex",
        "crypt-max": "ChatGPT 5.5",
        "crypt-balanced": "ChatGPT 5.4",
        "crypt-fast": "ChatGPT 5.4 Mini",
        "crypt-legacy": "ChatGPT 5.3 Codex",
        "crypt-spark": "ChatGPT 5.3 Spark",
        "crypt-mini": "Codex Mini",
        "gpt-5-codex": "ChatGPT 5 Codex",
        "gpt-5.3-codex": "ChatGPT 5.3 Codex",
        "gpt-5.3-codex-spark": "ChatGPT 5.3 Spark",
        "gpt-5.4-mini": "ChatGPT 5.4 Mini",
        "gpt-5.4": "ChatGPT 5.4",
        "gpt-5.5": "ChatGPT 5.5",
    }
    raw = str(model or "")
    if raw in labels:
        return labels[raw]
    return " ".join(part.capitalize() for part in raw.replace(":", " ").replace("_", " ").replace("-", " ").split())


def _display_provider_label(provider_id: str, snapshot: dict) -> str:
    providers = snapshot.get("providers") if isinstance(snapshot.get("providers"), list) else []
    for provider in providers:
        if str(provider.get("id") or "") == provider_id:
            return str(provider.get("label") or provider_id)
    return provider_id


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
    intent: intent_router.IntentRoute | None = None,
    action: clarification_policy.ActionDecision | None = None,
    workspace: str | Path | None = None,
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
    if intent:
        hint = intent_router.prompt_hint(intent)
        if hint:
            hints.append(hint)
    if action:
        hints.append(clarification_policy.prompt_hint(action))
    if business_mission.is_business_text(text):
        hints.append(business_mission.prompt_section().replace("\n", " | "))
    if workspace:
        section = mission_brain.prompt_section(workspace)
        if section:
            hints.append(section.replace("\n", " | "))
        schedule_section = scheduler.prompt_section(workspace)
        if schedule_section:
            hints.append(schedule_section.replace("\n", " | "))
        monitor_section = monitors.prompt_section(workspace)
        if monitor_section:
            hints.append(monitor_section.replace("\n", " | "))
        revenue_section = revenue.prompt_section(workspace)
        if revenue_section:
            hints.append(revenue_section.replace("\n", " | "))
        entity_section = entities.prompt_section(workspace)
        if entity_section:
            hints.append(entity_section.replace("\n", " | "))
        graph_section = knowledge_graph.prompt_section(workspace, text=text)
        if graph_section:
            hints.append(graph_section.replace("\n", " | "))
        context_section = context_packs.prompt_section(workspace, text, budget_tokens=1_400)
        if context_section:
            hints.append(context_section.replace("\n", " | "))
        upgrade_section = upgrade_queue.prompt_section(workspace)
        if upgrade_section:
            hints.append(upgrade_section.replace("\n", " | "))
        rebuild_section = runtime_rebuild.prompt_section(workspace)
        if rebuild_section:
            hints.append(rebuild_section.replace("\n", " | "))
        gateway_section = mcp_gateway.prompt_section(workspace)
        if gateway_section:
            hints.append(gateway_section.replace("\n", " | "))
        builder_section = code_builder.prompt_section(workspace, text)
        if builder_section:
            hints.append(builder_section.replace("\n", " | "))
    if not hints:
        return text
    return f"{text}\n\n[Crypt runtime hints: {'; '.join(hints)}]"
