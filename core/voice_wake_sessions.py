"""Voice wake-session state for local chat voice mode."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import redact, session, settings


SCHEMA_VERSION = 1
MAX_EVENTS = 80
MAX_SESSIONS = 20
EVENTS = {"started", "stopped", "transcript", "reply", "interrupted", "confirmation", "preference", "wake", "error"}
WAKE_RE = re.compile(r"\b(?:hey|yo|okay|ok|alright|wake up)?\s*crypt\b", re.I)
CONFIRM_RE = re.compile(r"\b(yes|yeah|yep|yup|confirm|approved?|go ahead|do it|send it|run it|launch it|that's fine|sounds good)\b", re.I)
PREFERENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("voice", re.compile(r"\b(?:voice|speak|speech|tts)\b.{0,90}\b(?:slower|faster|shorter|deeper|warmer|natural|realistic|louder|quieter|no emojis?|don't pronounce emojis?)\b", re.I)),
    ("address", re.compile(r"\b(?:call me|my name is|refer to me as)\s+([A-Za-z][A-Za-z0-9_-]{1,30})\b", re.I)),
    ("wake", re.compile(r"\b(?:wake phrase|wake word|say hey crypt|listen when I say)\b.{0,100}", re.I)),
)


@dataclass(frozen=True)
class WakeEvent:
    event_id: str
    event: str
    text: str = ""
    voice: str = ""
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VoiceWakeSession:
    session_id: str
    cwd: str
    status: str = "idle"
    active_voice: str = ""
    wake_phrase_hits: int = 0
    confirmation_count: int = 0
    interruption_count: int = 0
    preference_count: int = 0
    transcript_count: int = 0
    last_wake_phrase: str = ""
    last_confirmation: str = ""
    last_transcript: str = ""
    preferences: list[str] = field(default_factory=list)
    events: list[WakeEvent] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "events": [event.to_dict() for event in self.events],
        }


def sessions_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "voice" / "wake_sessions.json"


def record_event(
    cwd: str | Path,
    event: str,
    *,
    text: str = "",
    conversation_id: str = "",
    voice: str = "",
) -> VoiceWakeSession:
    root = Path(cwd).expanduser().resolve()
    sessions = list_sessions(root, include_all=True)
    current = _current_session(root, sessions, conversation_id=conversation_id, event=event)
    clean_event = _event(event)
    clean_text = _clean(text, 1_000)
    clean_voice = _clean(voice, 80)
    now = _now()
    added_events = [
        WakeEvent(
            event_id="wake_evt_" + uuid.uuid4().hex[:10],
            event=clean_event,
            text=clean_text,
            voice=clean_voice,
            created_at=now,
        )
    ]
    status = _status_for(clean_event)
    wake_hits = current.wake_phrase_hits
    confirmations = current.confirmation_count
    interruptions = current.interruption_count
    preference_count = current.preference_count
    transcript_count = current.transcript_count
    last_wake = current.last_wake_phrase
    last_confirmation = current.last_confirmation
    last_transcript = current.last_transcript
    preferences = list(current.preferences)

    if clean_event == "transcript" and clean_text:
        transcript_count += 1
        last_transcript = clean_text
        wake_phrase = _wake_phrase(clean_text)
        if wake_phrase:
            wake_hits += 1
            last_wake = wake_phrase
            added_events.insert(0, _signal_event("wake", wake_phrase, clean_voice, now))
        if _is_confirmation(clean_text):
            confirmations += 1
            last_confirmation = clean_text
            added_events.insert(0, _signal_event("confirmation", clean_text, clean_voice, now))
        for preference in _preferences(clean_text):
            if preference not in preferences:
                preferences.insert(0, preference)
                preference_count += 1
                added_events.insert(0, _signal_event("preference", preference, clean_voice, now))
    elif clean_event == "confirmation" and clean_text:
        confirmations += 1
        last_confirmation = clean_text
    elif clean_event == "interrupted":
        interruptions += 1
    elif clean_event == "preference" and clean_text and clean_text not in preferences:
        preferences.insert(0, clean_text)
        preference_count += 1

    updated = replace(
        current,
        status=status,
        active_voice=clean_voice or current.active_voice,
        wake_phrase_hits=wake_hits,
        confirmation_count=confirmations,
        interruption_count=interruptions,
        preference_count=preference_count,
        transcript_count=transcript_count,
        last_wake_phrase=last_wake,
        last_confirmation=last_confirmation,
        last_transcript=last_transcript,
        preferences=preferences[:20],
        events=[*added_events, *current.events][:MAX_EVENTS],
        updated_at=now,
    )
    rows = [row for row in sessions if row.session_id != updated.session_id]
    rows.insert(0, updated)
    _write(root, rows[:MAX_SESSIONS])
    return updated


def list_sessions(cwd: str | Path, *, include_all: bool = False, limit: int = 20) -> list[VoiceWakeSession]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status != "idle"]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_sessions(cwd, include_all=True, limit=20)
    active = rows[0] if rows else _new(Path(cwd).expanduser().resolve())
    return {
        "schema": SCHEMA_VERSION,
        "status": active.status,
        "sessionId": active.session_id,
        "activeVoice": active.active_voice,
        "wakePhraseHits": active.wake_phrase_hits,
        "confirmationCount": active.confirmation_count,
        "interruptionCount": active.interruption_count,
        "preferenceCount": active.preference_count,
        "lastWakePhrase": active.last_wake_phrase,
        "lastConfirmation": active.last_confirmation,
        "lastTranscript": active.last_transcript,
        "preferences": list(active.preferences[:12]),
        "events": [event.to_dict() for event in active.events[:12]],
        "sessions": [row.to_dict() for row in rows[:8]],
    }


def prompt_section(cwd: str | Path) -> str:
    snap = snapshot(cwd)
    lines = [
        "# Voice Wake Session Layer",
        (
            f"- status={snap['status']}; wake_hits={snap['wakePhraseHits']}; "
            f"confirmations={snap['confirmationCount']}; interruptions={snap['interruptionCount']}"
        ),
        "- When the user says a wake phrase, treat the next voice input as intentional and keep replies concise.",
        "- If interrupted, stop speaking and listen before continuing.",
    ]
    if snap["preferences"]:
        lines.append("- voice preferences: " + "; ".join(snap["preferences"][:4]))
    if snap["lastConfirmation"]:
        lines.append(f"- last voice confirmation: {snap['lastConfirmation'][:180]}")
    return "\n".join(lines)


def _current_session(root: Path, rows: list[VoiceWakeSession], *, conversation_id: str, event: str) -> VoiceWakeSession:
    clean_id = _clean(conversation_id, 120)
    if clean_id:
        for row in rows:
            if row.session_id == clean_id:
                return row
        return _new(root, session_id=clean_id)
    if _event(event) == "started":
        return _new(root)
    return rows[0] if rows else _new(root)


def _new(root: Path, *, session_id: str = "") -> VoiceWakeSession:
    now = _now()
    return VoiceWakeSession(
        session_id=session_id or "wake_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        created_at=now,
        updated_at=now,
    )


def _read(cwd: str | Path) -> list[VoiceWakeSession]:
    path = sessions_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("sessions", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                VoiceWakeSession(
                    session_id=str(item.get("session_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    status=str(item.get("status") or "idle"),
                    active_voice=str(item.get("active_voice") or ""),
                    wake_phrase_hits=int(item.get("wake_phrase_hits") or 0),
                    confirmation_count=int(item.get("confirmation_count") or 0),
                    interruption_count=int(item.get("interruption_count") or 0),
                    preference_count=int(item.get("preference_count") or 0),
                    transcript_count=int(item.get("transcript_count") or 0),
                    last_wake_phrase=str(item.get("last_wake_phrase") or ""),
                    last_confirmation=str(item.get("last_confirmation") or ""),
                    last_transcript=str(item.get("last_transcript") or ""),
                    preferences=[_clean(str(value), 180) for value in item.get("preferences", []) if str(value).strip()],
                    events=[
                        WakeEvent(
                            event_id=str(raw.get("event_id") or ""),
                            event=_event(str(raw.get("event") or "transcript")),
                            text=str(raw.get("text") or ""),
                            voice=str(raw.get("voice") or ""),
                            created_at=int(raw.get("created_at") or 0),
                        )
                        for raw in item.get("events", [])
                        if isinstance(raw, dict)
                    ][:MAX_EVENTS],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.session_id and row.cwd]


def _write(cwd: str | Path, rows: list[VoiceWakeSession]) -> None:
    path = sessions_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "sessions": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _signal_event(event: str, text: str, voice: str, now: int) -> WakeEvent:
    return WakeEvent(
        event_id="wake_evt_" + uuid.uuid4().hex[:10],
        event=event,
        text=_clean(text, 1_000),
        voice=voice,
        created_at=now,
    )


def _wake_phrase(text: str) -> str:
    match = WAKE_RE.search(text)
    return _clean(match.group(0), 80) if match else ""


def _is_confirmation(text: str) -> bool:
    return bool(CONFIRM_RE.search(text))


def _preferences(text: str) -> list[str]:
    out = []
    for label, pattern in PREFERENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            out.append(f"{label}: {_clean(match.group(0), 160)}")
    return out


def _status_for(event: str) -> str:
    return {
        "started": "listening",
        "stopped": "idle",
        "transcript": "heard",
        "reply": "speaking",
        "interrupted": "interrupted",
        "confirmation": "confirming",
        "preference": "heard",
        "wake": "listening",
        "error": "error",
    }[event]


def _event(value: str) -> str:
    clean = str(value or "transcript").strip().lower()
    return clean if clean in EVENTS else "transcript"


def _clean(value: str, limit: int) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
