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


def observe(cwd: str | Path, text: str, *, source: str = "webui") -> PassiveMemoryResult:
    """Persist useful user signals without requiring a manual memory form.

    This is intentionally conservative. It captures preferences, product
    direction, persona feedback, and recurring workflow cues, while ignoring
    empty chatter and throwaway one-liners.
    """
    clean = _clean(text)
    if not _should_capture(clean):
        return PassiveMemoryResult(False)

    tags = tuple(_tags_for(clean))
    confidence = 0.78 if "preference" in tags or "persona" in tags else 0.66
    lesson = learning.add_lesson(
        _memory_text(clean),
        cwd=cwd,
        scope="project",
        tags=list(tags),
        confidence=confidence,
        source=source,
    )
    update = soul.evolve(cwd)
    return PassiveMemoryResult(
        True,
        lesson_id=lesson.lesson_id,
        text=lesson.text,
        tags=tags,
        soul_changed=update.changed,
    )


def _should_capture(text: str) -> bool:
    if not text or IGNORE_RE.match(text):
        return False
    words = text.split()
    return len(words) >= MIN_WORDS or bool(STRONG_MEMORY_RE.search(text))


def _tags_for(text: str) -> list[str]:
    lowered = text.lower()
    tags = ["passive", "chat"]
    if any(token in lowered for token in ("i want", "i like", "i hate", "i prefer", "always", "never", "should")):
        tags.append("preference")
    if any(token in lowered for token in ("crypt", "persona", "soul", "voice", "tone", "homie", "robot")):
        tags.append("persona")
    if any(token in lowered for token in ("ui", "webui", "panel", "dropdown", "chat", "model")):
        tags.append("ui")
    if any(token in lowered for token in ("business", "income", "revenue", "customer", "website")):
        tags.append("business")
    if any(token in lowered for token in ("agent", "provider", "model", "route")):
        tags.append("agent")
    if any(token in lowered for token in ("openclaw", "hermes", "aionui")):
        tags.append("reference")
    return tags


def _memory_text(text: str) -> str:
    if text.lower().startswith(("crypt should", "always", "never", "remember")):
        return text
    return f"User signal: {text}"


def _clean(text: str) -> str:
    clean = " ".join(str(text or "").split())
    return clean[:MAX_MEMORY_CHARS].rstrip()
