"""Durable voice conversation state for the local WebUI."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import memory_journal, session, settings


SCHEMA_VERSION = 1
EVENTS = {"started", "stopped", "transcript", "reply", "interrupted", "error"}


@dataclass(frozen=True)
class VoiceEvent:
    event_id: str
    event: str
    text: str = ""
    created_at: int = 0


@dataclass(frozen=True)
class VoiceConversation:
    conversation_id: str
    cwd: str
    status: str = "idle"
    turn_count: int = 0
    last_user_text: str = ""
    last_reply_text: str = ""
    interruption_count: int = 0
    memory_updates: int = 0
    short_reply_hint: str = "Voice mode: answer in 1-3 direct sentences unless the user asks for detail."
    events: list[VoiceEvent] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "events": [asdict(event) for event in self.events],
        }


def state_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "voice" / "conversation.json"


def record_event(
    cwd: str | Path,
    event: str,
    *,
    text: str = "",
    conversation_id: str = "",
) -> VoiceConversation:
    root = Path(cwd).expanduser().resolve()
    current = load(root)
    clean_event = _event(event)
    if conversation_id and current.conversation_id != conversation_id:
        current = _new(root, conversation_id=conversation_id)
    clean_text = _clean(text, 1_500)
    now = _now()
    voice_event = VoiceEvent(
        event_id="voice_evt_" + uuid.uuid4().hex[:10],
        event=clean_event,
        text=clean_text,
        created_at=now,
    )
    status = {
        "started": "listening",
        "stopped": "idle",
        "transcript": "heard",
        "reply": "speaking",
        "interrupted": "interrupted",
        "error": "error",
    }[clean_event]
    memory_updates = current.memory_updates
    turn_count = current.turn_count
    last_user = current.last_user_text
    last_reply = current.last_reply_text
    interruptions = current.interruption_count
    if clean_event == "transcript" and clean_text:
        turn_count += 1
        last_user = clean_text
        memory = memory_journal.observe(root, clean_text, source="voice-conversation")
        memory_updates += 1 if memory.changed else 0
    elif clean_event == "reply" and clean_text:
        last_reply = clean_text
    elif clean_event == "interrupted":
        interruptions += 1
    updated = replace(
        current,
        status=status,
        turn_count=turn_count,
        last_user_text=last_user,
        last_reply_text=last_reply,
        interruption_count=interruptions,
        memory_updates=memory_updates,
        events=[voice_event, *current.events][:60],
        updated_at=now,
    )
    _write(root, updated)
    return updated


def load(cwd: str | Path) -> VoiceConversation:
    root = Path(cwd).expanduser().resolve()
    path = state_path(root)
    if not path.exists():
        return _new(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _new(root)
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return _new(root)
    item = data.get("conversation") or {}
    if not isinstance(item, dict):
        return _new(root)
    try:
        return VoiceConversation(
            conversation_id=str(item.get("conversation_id") or "voice_" + uuid.uuid4().hex[:10]),
            cwd=str(item.get("cwd") or root),
            status=str(item.get("status") or "idle"),
            turn_count=int(item.get("turn_count") or 0),
            last_user_text=str(item.get("last_user_text") or ""),
            last_reply_text=str(item.get("last_reply_text") or ""),
            interruption_count=int(item.get("interruption_count") or 0),
            memory_updates=int(item.get("memory_updates") or 0),
            short_reply_hint=str(item.get("short_reply_hint") or "Voice mode: answer in 1-3 direct sentences unless the user asks for detail."),
            events=[
                VoiceEvent(
                    event_id=str(event.get("event_id") or ""),
                    event=_event(str(event.get("event") or "transcript")),
                    text=str(event.get("text") or ""),
                    created_at=int(event.get("created_at") or 0),
                )
                for event in item.get("events", [])
                if isinstance(event, dict)
            ][:60],
            created_at=int(item.get("created_at") or 0),
            updated_at=int(item.get("updated_at") or 0),
        )
    except Exception:
        return _new(root)


def snapshot(cwd: str | Path) -> dict[str, Any]:
    convo = load(cwd)
    return {
        "conversationId": convo.conversation_id,
        "status": convo.status,
        "turnCount": convo.turn_count,
        "interruptionCount": convo.interruption_count,
        "memoryUpdates": convo.memory_updates,
        "lastUserText": convo.last_user_text,
        "lastReplyText": convo.last_reply_text,
        "shortReplyHint": convo.short_reply_hint,
        "events": [asdict(event) for event in convo.events[:12]],
    }


def prompt_section(cwd: str | Path) -> str:
    convo = load(cwd)
    lines = [
        "# Voice Conversation Mode",
        f"- status={convo.status}; turns={convo.turn_count}; interruptions={convo.interruption_count}",
        f"- {convo.short_reply_hint}",
        "- If the user speaks while audio is playing, treat it as an interruption and stop speaking before listening.",
    ]
    if convo.last_user_text:
        lines.append(f"- last voice transcript: {convo.last_user_text[:220]}")
    return "\n".join(lines)


def _new(root: Path, *, conversation_id: str = "") -> VoiceConversation:
    now = _now()
    return VoiceConversation(
        conversation_id=conversation_id or "voice_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        created_at=now,
        updated_at=now,
    )


def _write(cwd: str | Path, convo: VoiceConversation) -> None:
    path = state_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": SCHEMA_VERSION, "conversation": convo.to_dict()}, indent=2), encoding="utf-8")
    settings.restrict_file_permissions(path)


def _event(value: str) -> str:
    clean = str(value or "transcript").strip().lower()
    return clean if clean in EVENTS else "transcript"


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
