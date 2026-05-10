"""Durable session transcripts for Crypt.

Sessions are append-only JSONL files under ``~/.crypt/projects/<project>/``.
Only provider-facing messages are replayed into the model; metadata entries
make resume/search usable without polluting the conversation.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import redact, settings


SESSION_SCHEMA_VERSION = 1


def _now() -> int:
    return int(time.time())


def _project_slug(cwd: str | Path) -> str:
    path = str(Path(cwd).expanduser().resolve())
    digest = hashlib.sha1(path.encode("utf-8", errors="replace")).hexdigest()[:12]
    name = Path(path).name or "root"
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in name).strip(".-")
    return f"{safe or 'project'}-{digest}"


def project_dir(cwd: str | Path) -> Path:
    return settings.APP_DIR / "projects" / _project_slug(cwd)


def session_path(cwd: str | Path, session_id: str) -> Path:
    return project_dir(cwd) / f"{session_id}.jsonl"


def _json_line(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    out.append(item)
    except OSError:
        return []
    return out


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif block.get("type") == "tool_use":
            parts.append(f"[tool_use:{block.get('name', '')}]")
        elif block.get("type") == "tool_result":
            parts.append(f"[tool_result:{block.get('tool_use_id', '')}]")
    return "\n".join(p for p in parts if p).strip()


@dataclass
class SessionInfo:
    session_id: str
    path: Path
    cwd: str
    created_at: int = 0
    updated_at: int = 0
    provider: str = ""
    model: str = ""
    title: str = ""
    last_user: str = ""
    message_count: int = 0


class Session:
    def __init__(
        self,
        cwd: str | Path,
        session_id: str | None = None,
        provider: str = "",
        model: str = "",
        resume: bool = False,
    ) -> None:
        self.cwd = str(Path(cwd).expanduser().resolve())
        self.id = session_id or str(uuid.uuid4())
        self.path = session_path(self.cwd, self.id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.provider = provider
        self.model = model
        if not resume or not self.path.exists():
            self.append({
                "type": "meta",
                "schema": SESSION_SCHEMA_VERSION,
                "session_id": self.id,
                "cwd": self.cwd,
                "provider": provider,
                "model": model,
                "created_at": _now(),
            })
        else:
            self.append({
                "type": "event",
                "event": "resumed",
                "session_id": self.id,
                "cwd": self.cwd,
                "provider": provider,
                "model": model,
                "ts": _now(),
            })

    def append(self, entry: dict[str, Any]) -> None:
        entry.setdefault("ts", _now())
        tmp = _json_line(entry)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(tmp)
        settings.restrict_file_permissions(self.path)

    def record_message(self, message: dict[str, Any]) -> None:
        safe_message = _redacted_message(message)
        self.append({"type": "message", "message": safe_message})
        if safe_message.get("role") == "user":
            text = _message_text(safe_message)
            if text:
                self.append({"type": "last_user", "text": text[:5000]})
                if not self.info().title:
                    self.append({"type": "title", "text": _title_from_text(text)})

    def record_compaction(self, summary: str, kept_messages: int, messages: list[dict[str, Any]] | None = None) -> None:
        self.append({
            "type": "compact",
            "summary": redact.text(summary),
            "kept_messages": kept_messages,
        })
        if messages is not None:
            self.append({
                "type": "snapshot",
                "reason": "compact",
                "messages": [_redacted_message(msg) for msg in messages],
            })

    def load_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for entry in _read_jsonl(self.path):
            if entry.get("type") == "message" and isinstance(entry.get("message"), dict):
                msg = entry["message"]
                if msg.get("role") in ("user", "assistant"):
                    messages.append(msg)
            elif entry.get("type") == "snapshot" and isinstance(entry.get("messages"), list):
                messages = [
                    msg for msg in entry["messages"]
                    if isinstance(msg, dict) and msg.get("role") in ("user", "assistant")
                ]
        return messages

    def info(self) -> SessionInfo:
        return info_from_path(self.path)


def _title_from_text(text: str, limit: int = 64) -> str:
    line = " ".join(text.strip().split())
    if not line:
        return "untitled"
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "."


def _redacted_message(message: dict[str, Any]) -> dict[str, Any]:
    safe = redact.content(message)
    return safe if isinstance(safe, dict) else dict(message)


def info_from_path(path: Path) -> SessionInfo:
    info = SessionInfo(session_id=path.stem, path=path, cwd="")
    try:
        st = path.stat()
        info.updated_at = int(st.st_mtime)
    except OSError:
        return info

    for entry in _read_jsonl(path):
        typ = entry.get("type")
        if typ == "meta":
            info.cwd = str(entry.get("cwd") or info.cwd)
            info.provider = str(entry.get("provider") or info.provider)
            info.model = str(entry.get("model") or info.model)
            info.created_at = int(entry.get("created_at") or entry.get("ts") or info.created_at)
        elif typ == "message":
            info.message_count += 1
        elif typ == "title":
            info.title = str(entry.get("text") or info.title)
        elif typ == "last_user":
            info.last_user = str(entry.get("text") or info.last_user)
    if not info.created_at:
        info.created_at = info.updated_at
    if not info.title and info.last_user:
        info.title = _title_from_text(info.last_user)
    return info


def list_sessions(cwd: str | Path | None = None, all_projects: bool = False) -> list[SessionInfo]:
    roots: list[Path]
    if all_projects:
        base = settings.APP_DIR / "projects"
        roots = [p for p in base.iterdir() if p.is_dir()] if base.exists() else []
    else:
        roots = [project_dir(cwd or Path.cwd())]

    infos: list[SessionInfo] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*.jsonl"):
            infos.append(info_from_path(path))
    infos.sort(key=lambda i: i.updated_at, reverse=True)
    return infos


def find_session(cwd: str | Path, query: str | None = None) -> SessionInfo | None:
    sessions = list_sessions(cwd)
    if not sessions:
        return None
    if not query or query in ("last", "latest"):
        return sessions[0]
    query_l = query.lower()
    for item in sessions:
        if item.session_id.startswith(query) or query_l in item.title.lower():
            return item
    return None


def load_session(cwd: str | Path, session_id: str, provider: str = "", model: str = "") -> Session:
    return Session(cwd, session_id=session_id, provider=provider, model=model, resume=True)
