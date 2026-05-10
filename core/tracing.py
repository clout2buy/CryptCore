"""Structured trace logging for agent runs.

Traces are compact JSONL events intended for debugging, benchmark grading,
and post-run audit. They are deliberately best-effort: tracing must never
break a user task.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from . import redact, settings


TRACE_SCHEMA_VERSION = 1
TRACE_DIR = settings.APP_DIR / "traces"

_LOCK = threading.Lock()
_FALSEY = {"0", "false", "off", "no"}


def enabled() -> bool:
    return os.getenv("CRYPT_TRACE", "1").strip().lower() not in _FALSEY


def trace_path(session_id: str) -> Path:
    return TRACE_DIR / f"{session_id}.jsonl"


def emit(event: str, **fields: Any) -> None:
    """Append one JSON event to the active trace sink.

    The sink is ``CRYPT_TRACE_PATH`` when set, otherwise the current runtime
    session id is used. If neither exists, tracing is a no-op.
    """
    if not enabled():
        return
    try:
        path = _active_path()
        if path is None:
            return
        entry = _entry(event, fields)
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
            settings.restrict_file_permissions(path)
    except Exception:
        return


def read(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                out.append(item)
    return out


def _active_path() -> Path | None:
    raw = os.getenv("CRYPT_TRACE_PATH")
    if raw:
        return Path(raw).expanduser().resolve()
    try:
        from . import runtime

        sid = runtime.session_id()
        if sid:
            return trace_path(sid)
    except Exception:
        return None
    return None


def _entry(event: str, fields: dict[str, Any]) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": TRACE_SCHEMA_VERSION,
        "ts": time.time(),
        "event": event,
    }
    try:
        from . import runtime

        provider = runtime.provider()
        sid = runtime.session_id()
        if sid:
            base["session_id"] = sid
        if runtime.cwd():
            base["cwd"] = runtime.cwd()
        if provider is not None:
            base["provider"] = getattr(provider, "name", "")
            base["model"] = getattr(provider, "model", "")
    except Exception:
        pass
    base.update(_jsonable(fields))
    return base


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return redact.text(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value[:200]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if _looks_sensitive_key(text_key):
                out[text_key] = "[redacted]"
            elif text_key in {"content", "new", "old"} and isinstance(item, str):
                out[text_key] = _clip(redact.text(item), 500)
            else:
                out[text_key] = _jsonable(item)
        return out
    return _clip(redact.text(str(value)), 1000)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "... [truncated]"


def _looks_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in ("token", "secret", "password", "api_key", "apikey", "authorization"))
