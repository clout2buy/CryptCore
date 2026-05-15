"""Lightweight passive memory capture for natural WebUI chat."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import learning, soul


MIN_WORDS = 7
MAX_MEMORY_CHARS = 420

STRONG_MEMORY_RE = re.compile(
    r"\b(remember|always|never|i want|i like|i hate|i prefer|my\b|crypt should|"
    r"persona|soul|voice|tone|homie|business|agent|model|provider|memory|"
    r"openclaw|hermes|aionui|ui|webui|autonom|learn)\b",
    re.IGNORECASE,
)
IGNORE_RE = re.compile(r"^(hi|hey|hello|yo|thanks|thank you|ok|okay|lol|lmao)[.!?\s]*$", re.IGNORECASE)


@dataclass(frozen=True)
class PassiveMemoryResult:
    learned: bool
    lesson_id: str = ""
    text: str = ""
    tags: tuple[str, ...] = ()
    soul_changed: bool = False
    category: str = ""
    confidence: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class MemoryDecision:
    capture: bool
    category: str = ""
    tags: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = ""


def observe(cwd: str | Path, text: str, *, source: str = "webui") -> PassiveMemoryResult:
    """Persist useful user signals without requiring a manual memory form.

    This is intentionally conservative. It captures preferences, product
    direction, persona feedback, and recurring workflow cues, while ignoring
    empty chatter and throwaway one-liners.
    """
    clean = _clean(text)
    decision = decide(clean)
    if not decision.capture:
        return PassiveMemoryResult(False, reason=decision.reason)

    lesson = learning.add_lesson(
        _memory_text(clean, decision.category),
        cwd=cwd,
        scope="project",
        tags=list(decision.tags),
        confidence=decision.confidence,
        source=source,
    )
    update = soul.evolve(cwd)
    return PassiveMemoryResult(
        True,
        lesson_id=lesson.lesson_id,
        text=lesson.text,
        tags=decision.tags,
        soul_changed=update.changed,
        category=decision.category,
        confidence=decision.confidence,
        reason=decision.reason,
    )


def decide(text: str) -> MemoryDecision:
    if not text or IGNORE_RE.match(text):
        return MemoryDecision(False, reason="trivial chat")
    words = text.split()
    category = _category_for(text)
    tags = tuple(_tags_for(text, category))
    strong = bool(STRONG_MEMORY_RE.search(text))
    recurring = "recurring" in tags
    operational = category in {"project", "tool", "business", "agent", "ui"}
    if text.endswith("?") and not strong and not recurring and len(words) < 14:
        return MemoryDecision(False, reason="short question, not durable memory")
    if len(words) < MIN_WORDS and not strong and not recurring:
        return MemoryDecision(False, reason="too little durable signal")
    if category == "conversation" and not strong and len(words) < 18:
        return MemoryDecision(False, reason="conversation without reusable signal")
    confidence = 0.82 if category in {"preference", "persona", "project"} else 0.70
    if recurring:
        confidence = max(confidence, 0.76)
    if operational:
        confidence = max(confidence, 0.68)
    return MemoryDecision(True, category=category, tags=tags, confidence=confidence, reason="durable user signal")


def _category_for(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("bug", "error", "fails", "workaround", "tool", "tts", "mic", "browser", "desktop")):
        return "tool"
    if any(token in lowered for token in ("crypt should", "persona", "soul", "voice", "tone", "homie", "robot")):
        return "persona"
    if any(token in lowered for token in ("i want", "i like", "i hate", "i prefer", "always", "never")):
        return "preference"
    if any(token in lowered for token in ("folder", "file", "repo", "repository", "project", "workspace", "path is", "saved at")):
        return "project"
    if any(token in lowered for token in ("business", "income", "revenue", "customer", "website")):
        return "business"
    if any(token in lowered for token in ("agent", "provider", "model", "route", "skill", "mcp")):
        return "agent"
    if any(token in lowered for token in ("ui", "webui", "panel", "dropdown", "chat")):
        return "ui"
    if any(token in lowered for token in ("openclaw", "hermes", "aionui")):
        return "reference"
    return "memory" if len(text.split()) >= 18 else "conversation"


def _tags_for(text: str, category: str = "") -> list[str]:
    lowered = text.lower()
    tags = ["passive", "chat"]
    if category and category not in {"conversation", "memory"}:
        tags.append(category)
    if any(token in lowered for token in ("i want", "i like", "i hate", "i prefer", "always", "never", "should")):
        tags.append("preference")
    if any(token in lowered for token in ("crypt", "persona", "soul", "voice", "tone", "homie", "robot")):
        tags.append("persona")
    if any(token in lowered for token in ("every time", "whenever", "daily", "weekly", "always", "never")):
        tags.append("recurring")
    if any(token in lowered for token in ("folder", "file", "repo", "repository", "workspace", "saved at")):
        tags.append("project")
    if any(token in lowered for token in ("bug", "error", "fails", "workaround", "tool", "mic", "tts")):
        tags.append("tool")
    if any(token in lowered for token in ("ui", "webui", "panel", "dropdown", "chat", "model")):
        tags.append("ui")
    if any(token in lowered for token in ("business", "income", "revenue", "customer", "website")):
        tags.append("business")
    if any(token in lowered for token in ("agent", "provider", "model", "route")):
        tags.append("agent")
    if any(token in lowered for token in ("openclaw", "hermes", "aionui")):
        tags.append("reference")
    return _dedupe(tags)


def _memory_text(text: str, category: str) -> str:
    if text.lower().startswith(("crypt should", "always", "never", "remember")):
        return text
    prefixes = {
        "preference": "User preference",
        "persona": "Crypt persona signal",
        "project": "Project fact",
        "tool": "Tool or workflow lesson",
        "business": "Business context",
        "agent": "Agent capability signal",
        "ui": "UI preference",
        "reference": "Reference signal",
    }
    if category in prefixes:
        return f"{prefixes[category]}: {text}"
    return f"User signal: {text}"


def _clean(text: str) -> str:
    clean = " ".join(str(text or "").split())
    return clean[:MAX_MEMORY_CHARS].rstrip()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = str(item or "").strip().lower()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out
