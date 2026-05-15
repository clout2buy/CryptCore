"""Self-maintained Markdown memory journal for Crypt.

The learning store keeps structured lessons. This module keeps the visible
memory artifact the user asked for: a local Markdown file Crypt updates from
normal conversation without requiring a special "remember this" command.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import memory_importance, redact, settings


SCHEMA_VERSION = 2
MAX_SIGNAL_CHARS = 520
MAX_LONG_TERM = 90
MAX_WORKING = 45
MAX_OPEN_LOOPS = 35
MEMORY_NAME = "CRYPT_MEMORY.md"
STATE_NAME = "memory_journal.json"

TRIVIAL_RE = re.compile(r"^(hi|hey|hello|yo|ok|okay|thanks|thank you|lol|lmao)[.!?\s]*$", re.I)
PROMOTE_RE = re.compile(
    r"\b("
    r"always|never|remember|i want|i need|i like|i hate|i prefer|crypt should|"
    r"persona|soul|voice|tone|homie|not.*robot|sassy|blunt|"
    r"autonom|mission|goal|thread|learn|memory|skill|agent|provider|model|"
    r"business|income|revenue|customer|website|email|reddit|post|monitor|track|"
    r"desktop|browser|mouse|screen|visual|tts|voice"
    r")\b",
    re.I,
)
OPEN_LOOP_RE = re.compile(
    r"\b("
    r"need to|should|next|todo|to do|fix|build|create|launch|monitor|track|"
    r"setup|set up|make sure|follow up|keep going|do it all"
    r")\b",
    re.I,
)
PERSONA_RE = re.compile(r"\b(crypt|persona|soul|voice|tone|homie|sassy|blunt|robot|conscious|sentien)\b", re.I)
SENSITIVE_RE = re.compile(
    r"\b(password|passcode|token|secret|api key|credential|login|email|phone|address|credit card|payment)\b|"
    r"\[redacted",
    re.I,
)
CORRECTION_RE = re.compile(r"\b(correction|actually|not that|instead|update this|change that)\b", re.I)


@dataclass(frozen=True)
class MemorySignal:
    signal_id: str
    text: str
    category: str
    memory_type: str = "memory"
    source: str = "webui"
    workspace: str = ""
    confidence: float = 0.5
    sensitivity: str = "normal"
    decay: str = "standard"
    hits: int = 1
    created_at: int = 0
    updated_at: int = 0
    tags: list[str] = field(default_factory=list)
    corrections: list[dict[str, Any]] = field(default_factory=list)
    importance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryJournalResult:
    changed: bool
    path: Path
    text: str = ""
    category: str = ""
    promoted: bool = False
    long_term_count: int = 0
    working_count: int = 0
    open_loop_count: int = 0


def memory_dir() -> Path:
    return settings.APP_DIR / "memory"


def memory_path() -> Path:
    return memory_dir() / MEMORY_NAME


def state_path() -> Path:
    return memory_dir() / STATE_NAME


def ensure_journal(cwd: str | Path | None = None) -> Path:
    state = _read_state()
    created = False
    if not state:
        state = _empty_state(cwd)
        _write_state(state)
        created = True
    if created or not memory_path().exists():
        _write_markdown(state)
    return memory_path()


def observe(cwd: str | Path, text: str, *, source: str = "webui") -> MemoryJournalResult:
    """Capture a user message into long-term memory or working context."""
    root = Path(cwd).expanduser().resolve()
    clean = _clean(text)
    path = ensure_journal(root)
    if not clean or TRIVIAL_RE.match(clean):
        status_data = snapshot(root)
        return MemoryJournalResult(
            False,
            path,
            long_term_count=int(status_data["longTermCount"]),
            working_count=int(status_data["workingCount"]),
            open_loop_count=int(status_data["openLoopCount"]),
        )

    state = _read_state() or _empty_state(root)
    now = _now()
    category = _category(clean)
    importance = memory_importance.score_text(clean, category=category, previous_hits=_previous_hits(state, clean))
    promoted = _should_promote(clean) or importance.promote
    signal = MemorySignal(
        signal_id=_signal_id(clean),
        text=clean,
        category=category,
        memory_type=_memory_type(category, clean),
        source=source,
        workspace=str(root),
        confidence=max(0.82 if promoted else 0.48, importance.confidence),
        sensitivity=_sensitivity(clean),
        decay=_decay(clean, promoted),
        created_at=now,
        updated_at=now,
        tags=_tags(clean, category),
        importance=importance.to_dict(),
    )

    changed = False
    bucket_name = "long_term" if promoted else "working"
    bucket = list(state.get(bucket_name, []))
    merged, updated_bucket = _merge_signal(bucket, signal)
    if updated_bucket != bucket:
        changed = True
        state[bucket_name] = _trim(updated_bucket, MAX_LONG_TERM if promoted else MAX_WORKING)
    if promoted and category == "persona":
        persona_bucket = list(state.get("persona", []))
        _, updated_persona = _merge_signal(persona_bucket, signal)
        if updated_persona != persona_bucket:
            changed = True
            state["persona"] = _trim(updated_persona, 35)
    if _is_open_loop(clean):
        loop_signal = MemorySignal(
            signal_id=_signal_id("loop:" + clean),
            text=_loop_text(clean),
            category="open-loop",
            memory_type="open-loop",
            source=source,
            workspace=str(root),
            confidence=0.72,
            sensitivity=_sensitivity(clean),
            decay="working",
            created_at=now,
            updated_at=now,
            tags=["open-loop", *signal.tags[:3]],
        )
        loops = list(state.get("open_loops", []))
        _, updated_loops = _merge_signal(loops, loop_signal)
        if updated_loops != loops:
            changed = True
            state["open_loops"] = _trim(updated_loops, MAX_OPEN_LOOPS)

    if changed:
        state["schema"] = SCHEMA_VERSION
        state["workspace"] = str(root)
        state["updated_at"] = now
        _write_state(state)
        _write_markdown(state)

    latest = merged if isinstance(merged, dict) else asdict(signal)
    return MemoryJournalResult(
        changed,
        path,
        text=str(latest.get("text") or clean),
        category=category,
        promoted=promoted,
        long_term_count=len(state.get("long_term", [])),
        working_count=len(state.get("working", [])),
        open_loop_count=len(state.get("open_loops", [])),
    )


def snapshot(cwd: str | Path | None = None, *, preview: int = 8) -> dict[str, Any]:
    path = ensure_journal(cwd)
    state = _read_state() or _empty_state(cwd)
    long_term = list(state.get("long_term", []))
    working = list(state.get("working", []))
    loops = list(state.get("open_loops", []))
    persona = list(state.get("persona", []))
    return {
        "path": str(path),
        "updatedAt": int(state.get("updated_at") or 0),
        "longTermCount": len(long_term),
        "workingCount": len(working),
        "openLoopCount": len(loops),
        "personaCount": len(persona),
        "typeCounts": _type_counts([*long_term, *working, *loops]),
        "longTermPreview": long_term[: max(1, preview)],
        "workingPreview": working[: max(1, preview // 2)],
        "openLoopPreview": loops[: max(1, preview // 2)],
        "personaPreview": persona[: max(1, preview // 2)],
    }


def prompt_section(cwd: str | Path, *, limit: int = 10) -> str:
    state = _read_state()
    if not state:
        return ""
    lines = ["# Crypt Memory Journal"]
    long_term = list(state.get("long_term", []))[:limit]
    working = list(state.get("working", []))[: max(2, limit // 2)]
    loops = list(state.get("open_loops", []))[: max(2, limit // 2)]
    if long_term:
        lines.append("## Long-Term")
        lines.extend(f"- [{item.get('category', 'memory')}] {item.get('text', '')}" for item in long_term)
    if loops:
        lines.append("## Open Loops")
        lines.extend(f"- {item.get('text', '')}" for item in loops)
    if working:
        lines.append("## Working Context")
        lines.extend(f"- {item.get('text', '')}" for item in working)
    return "\n".join(line for line in lines if line.strip())


def filter_signals(
    cwd: str | Path | None = None,
    *,
    memory_type: str = "",
    min_confidence: float = 0.0,
    include_sensitive: bool = True,
) -> list[dict[str, Any]]:
    ensure_journal(cwd)
    state = _read_state() or _empty_state(cwd)
    selected = [
        *list(state.get("long_term", [])),
        *list(state.get("working", [])),
        *list(state.get("open_loops", [])),
    ]
    out = []
    requested_type = str(memory_type or "").strip().lower()
    for item in selected:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("memory_type") or item.get("category") or "memory").lower()
        if requested_type and item_type != requested_type:
            continue
        if float(item.get("confidence") or 0.0) < min_confidence:
            continue
        if not include_sensitive and str(item.get("sensitivity") or "normal") != "normal":
            continue
        out.append(item)
    out.sort(key=lambda item: (float(item.get("confidence") or 0.0), int(item.get("updated_at") or 0)), reverse=True)
    return out


def _empty_state(cwd: str | Path | None) -> dict[str, Any]:
    workspace = str(Path(cwd).expanduser().resolve()) if cwd else ""
    return {
        "schema": SCHEMA_VERSION,
        "workspace": workspace,
        "updated_at": _now(),
        "long_term": [],
        "working": [],
        "open_loops": [],
        "persona": [],
    }


def _read_state() -> dict[str, Any]:
    path = state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    settings.restrict_file_permissions(path)


def _write_markdown(state: dict[str, Any]) -> None:
    path = memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    updated = int(state.get("updated_at") or _now())
    lines = [
        "# Crypt Memory",
        "",
        "_Local self-maintained memory. Crypt updates this from normal conversation._",
        "",
        f"- Updated: {_format_time(updated)}",
        f"- Workspace: {state.get('workspace') or 'global'}",
        "",
        "## Long-Term Memory",
        *_markdown_items(state.get("long_term", []), empty="No promoted long-term memories yet."),
        "",
        "## Persona Signals",
        *_markdown_items(state.get("persona", []), empty="No persona signals yet."),
        "",
        "## Open Loops",
        *_markdown_items(state.get("open_loops", []), empty="No open loops yet."),
        "",
        "## Working Context",
        *_markdown_items(state.get("working", []), empty="No working context yet."),
        "",
    ]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)
    settings.restrict_file_permissions(path)


def _markdown_items(items: object, *, empty: str) -> list[str]:
    if not isinstance(items, list) or not items:
        return [f"- {empty}"]
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "memory")
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        hits = int(item.get("hits") or 1)
        hit_text = f" (hits: {hits})" if hits > 1 else ""
        out.append(f"- [{category}] {text}{hit_text}")
    return out or [f"- {empty}"]


def _merge_signal(items: list[dict[str, Any]], signal: MemorySignal) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = asdict(signal)
    key = _fingerprint(signal.text)
    out: list[dict[str, Any]] = []
    merged = data
    found = False
    for item in items:
        if not isinstance(item, dict):
            continue
        existing_text = str(item.get("text") or "")
        if _fingerprint(existing_text) == key:
            item = dict(item)
            item.setdefault("memory_type", item.get("category") or signal.memory_type)
            item.setdefault("sensitivity", signal.sensitivity)
            item.setdefault("decay", signal.decay)
            item.setdefault("corrections", [])
            if CORRECTION_RE.search(signal.text) and signal.text != existing_text:
                corrections = list(item.get("corrections") or [])
                corrections.insert(0, {"at": signal.updated_at, "from": existing_text, "to": signal.text})
                item["corrections"] = corrections[:8]
                item["text"] = signal.text
            item["hits"] = int(item.get("hits") or 1) + 1
            item["updated_at"] = signal.updated_at
            item["confidence"] = max(float(item.get("confidence") or 0.0), signal.confidence)
            item["importance"] = signal.importance or item.get("importance", {})
            item["sensitivity"] = _max_sensitivity(str(item.get("sensitivity") or "normal"), signal.sensitivity)
            item["decay"] = signal.decay if signal.decay == "stable" else str(item.get("decay") or signal.decay)
            item["tags"] = _dedupe([*(item.get("tags") or []), *signal.tags])
            merged = item
            found = True
        out.append(item)
    if not found:
        out.insert(0, data)
    else:
        out.sort(key=lambda item: int(item.get("updated_at") or 0), reverse=True)
    return merged, out


def _trim(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    ordered = sorted(items, key=lambda item: int(item.get("updated_at") or 0), reverse=True)
    return ordered[:limit]


def _should_promote(text: str) -> bool:
    words = text.split()
    return bool(PROMOTE_RE.search(text)) or len(words) >= 18


def _previous_hits(state: dict[str, Any], text: str) -> int:
    key = _fingerprint(text)
    hits = 0
    for bucket in ("long_term", "working", "open_loops"):
        for item in state.get(bucket, []):
            if not isinstance(item, dict):
                continue
            if _fingerprint(str(item.get("text") or "")) == key:
                hits = max(hits, int(item.get("hits") or 1))
    return hits


def _memory_type(category: str, text: str) -> str:
    lower = text.lower()
    if category == "persona":
        return "persona"
    if category == "open-loop":
        return "open-loop"
    if any(term in lower for term in ("always", "never", "prefer", "i want", "i need", "crypt should")):
        return "preference"
    if any(term in lower for term in ("folder", "file", "repo", "workspace", "path", "saved at")):
        return "project-fact"
    if any(term in lower for term in ("bug", "error", "fails", "workaround", "tool", "tts", "mic", "browser")):
        return "tool-quirk"
    if any(term in lower for term in ("daily", "weekly", "monthly", "whenever", "every time")):
        return "recurring"
    return category or "memory"


def _sensitivity(text: str) -> str:
    return "private" if SENSITIVE_RE.search(text) else "normal"


def _max_sensitivity(left: str, right: str) -> str:
    order = {"normal": 0, "private": 1}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _decay(text: str, promoted: bool) -> str:
    if promoted and any(term in text.lower() for term in ("always", "never", "prefer", "crypt should", "folder", "repo")):
        return "stable"
    if promoted:
        return "long"
    return "working"


def _type_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("memory_type") or item.get("category") or "memory")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _is_open_loop(text: str) -> bool:
    return bool(OPEN_LOOP_RE.search(text)) and len(text.split()) >= 4


def _loop_text(text: str) -> str:
    clean = text
    clean = re.sub(r"^(ok|okay|alright|so|please|can you|could you)\s+", "", clean, flags=re.I)
    return clean[:MAX_SIGNAL_CHARS].rstrip()


def _category(text: str) -> str:
    lower = text.lower()
    if PERSONA_RE.search(text):
        return "persona"
    if any(term in lower for term in ("ui", "webui", "panel", "dropdown", "chat", "screen")):
        return "ui"
    if any(term in lower for term in ("business", "income", "revenue", "customer", "email", "reddit", "post")):
        return "business"
    if any(term in lower for term in ("agent", "provider", "model", "route", "skill", "mcp")):
        return "agent"
    if any(term in lower for term in ("desktop", "browser", "mouse", "visual")):
        return "operation"
    return "memory"


def _tags(text: str, category: str) -> list[str]:
    lower = text.lower()
    tags = [category]
    if any(term in lower for term in ("always", "never", "prefer", "i want", "i need", "crypt should")):
        tags.append("preference")
    if "autonom" in lower or "do it all" in lower or "without me" in lower:
        tags.append("autonomy")
    if any(term in lower for term in ("track", "monitor", "watch", "due", "review")):
        tags.append("monitor")
    return _dedupe(tags)


def _fingerprint(text: str) -> str:
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2
        and word not in {"the", "and", "for", "you", "with", "that", "this", "should", "actually", "correction", "instead"}
    ]
    return " ".join(words[:40])


def _signal_id(text: str) -> str:
    import hashlib

    return "mem_" + hashlib.sha1(_fingerprint(text).encode("utf-8")).hexdigest()[:12]


def _clean(text: str) -> str:
    clean = " ".join(redact.text(str(text or "")).split())
    return clean[:MAX_SIGNAL_CHARS].rstrip()


def _dedupe(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = str(item or "").strip().lower()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _format_time(value: int) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))
    except Exception:
        return "unknown"


def _now() -> int:
    return int(time.time())
