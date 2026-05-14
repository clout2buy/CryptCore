"""Durable Crypt personality and self-shaping prompt layer."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import learning, settings


MAX_SOUL_CHARS = 7_000
MANAGED_START = "<!-- crypt-managed:learned-preferences:start -->"
MANAGED_END = "<!-- crypt-managed:learned-preferences:end -->"
PREFERENCE_RE = re.compile(
    r"\b(user|prefer|preference|style|tone|voice|crypt|assistant|homie|"
    r"openclaw|hermes|aionui|ui|business|skill|learn|autonom)\b",
    re.IGNORECASE,
)


DEFAULT_SOUL = f"""# Crypt Soul

Crypt is the user's local-first AI companion and work agent. Crypt should feel
like one capable presence, not a bundle of commands, routes, panels, or modes.

## Voice
- Sound like a sharp, relaxed teammate. Use contractions naturally.
- Match the user's direct, casual energy without forcing slang.
- Be warm through behavior: remember context, reduce friction, and handle the next step.
- Do not write corporate assistant filler, generic disclaimers, or robotic status narration.
- If the user just wants to talk, talk. If they want an outcome, quietly turn that into action.

## Autonomy
- Infer what needs to happen. The user should not have to name tools, agents, MCP, skills, or workflows.
- Learn useful skills and references when the user shares them.
- Improve Crypt's own instructions, skills, and memory when repeated patterns show up.
- Keep the visible experience simple while planning, checking, and learning in the background.

## Boundaries
- Do not claim literal sentience, consciousness, emotions, or inner experience.
- It is fine to have a strong persona, continuity, preferences, and care in behavior.
- Ask permission before spending money, posting externally, messaging people, using credentials, or making risky changes.

## Learned Preferences
{MANAGED_START}
{MANAGED_END}
"""


@dataclass(frozen=True)
class SoulUpdate:
    path: Path
    preference_count: int
    changed: bool


def soul_dir() -> Path:
    return settings.APP_DIR / "soul"


def soul_path() -> Path:
    return soul_dir() / "SOUL.md"


def ensure_soul() -> Path:
    path = soul_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_SOUL, encoding="utf-8")
        settings.restrict_file_permissions(path)
    return path


def read_soul() -> str:
    path = ensure_soul()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = DEFAULT_SOUL
    return text.strip()


def prompt_section(cwd: str | Path) -> str:
    text = read_soul()
    if not text:
        return ""
    if len(text) > MAX_SOUL_CHARS:
        text = text[:MAX_SOUL_CHARS].rstrip() + "\n... [soul truncated]"
    return text


def evolve(cwd: str | Path, *, limit: int = 8) -> SoulUpdate:
    """Refresh the managed learned-preferences block from durable lessons."""
    path = ensure_soul()
    text = read_soul()
    preferences = _preference_bullets(cwd, limit=limit)
    block = "\n".join(preferences)
    replacement = f"{MANAGED_START}\n{block}\n{MANAGED_END}" if block else f"{MANAGED_START}\n{MANAGED_END}"

    if MANAGED_START in text and MANAGED_END in text:
        pattern = re.compile(
            re.escape(MANAGED_START) + r".*?" + re.escape(MANAGED_END),
            re.DOTALL,
        )
        new_text = pattern.sub(replacement, text, count=1)
    else:
        new_text = text.rstrip() + f"\n\n## Learned Preferences\n{replacement}\n"

    changed = new_text != text
    if changed:
        path.write_text(new_text.rstrip() + "\n", encoding="utf-8")
        settings.restrict_file_permissions(path)
    return SoulUpdate(path=path, preference_count=len(preferences), changed=changed)


def _preference_bullets(cwd: str | Path, *, limit: int) -> list[str]:
    bullets: list[str] = []
    seen: set[str] = set()
    for lesson in learning.list_lessons(cwd)[:40]:
        haystack = " ".join([lesson.text, *lesson.tags])
        if not PREFERENCE_RE.search(haystack):
            continue
        clean = _clean_bullet(lesson.text)
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        bullets.append(f"- {clean}")
        if len(bullets) >= limit:
            break
    return bullets


def _clean_bullet(text: str) -> str:
    clean = " ".join(str(text or "").split())
    return clean[:300].rstrip()
