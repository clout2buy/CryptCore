"""Small local WebUI server for CryptCore."""
from __future__ import annotations

import json
import mimetypes
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

from . import app_daemon, autonomy, goals, learning, project_index, reflection, skill_forge


MAX_EVENTS = 500


class CryptWebServer(ThreadingHTTPServer):
    def __init__(self, server_address, *, cwd: str | Path):
        super().__init__(server_address, CryptWebHandler)
        self.cwd = Path(cwd).expanduser().resolve()
        self.events: list[dict] = []
        self.event_lock = threading.Lock()
        self.daemon = app_daemon.AppDaemon(emit=self.emit_event, cwd=str(self.cwd))

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
            self.server.daemon.handle_command(
                {
                    "type": "sendPrompt",
                    "id": request_id,
                    "text": text,
                    "route": str(body.get("route") or ""),
                    "sessionKey": str(body.get("sessionKey") or "web"),
                }
            )
            self._json({"id": request_id})
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
        snapshot["project"] = asdict(project_index.get(self.server.cwd))
        snapshot["goals"] = [asdict(goal) for goal in goals.list_goals(self.server.cwd, include_all=True)[:8]]
        snapshot["lessonsPreview"] = [asdict(lesson) for lesson in learning.list_lessons(self.server.cwd)[:8]]
        snapshot["reflections"] = [asdict(item) for item in reflection.list_reflections(self.server.cwd, limit=5)]
        snapshot["autonomy"] = [asdict(item) for item in autonomy.list_cycles(self.server.cwd, limit=5)]
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


def make_server(host: str, port: int, *, cwd: str | Path) -> CryptWebServer:
    return CryptWebServer((host, port), cwd=cwd)


def run(*, host: str, port: int, cwd: str | Path, open_browser: bool = False) -> int:
    server = make_server(host, port, cwd=cwd)
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
