"""Promote repeated learned lessons into project-local SKILL.md bundles."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import learning, redact


MIN_LESSONS = 2


@dataclass(frozen=True)
class ForgeResult:
    path: Path
    skill_name: str
    lesson_count: int
    created: bool


def forge_skill(
    cwd: str | Path,
    *,
    topic: str = "",
    name: str = "",
    min_lessons: int = MIN_LESSONS,
) -> ForgeResult:
    root = Path(cwd).expanduser().resolve()
    lessons = learning.search_lessons(root, topic, limit=20) if topic else learning.list_lessons(root)[:20]
    lessons = [lesson for lesson in lessons if lesson.confidence >= 0.5]
    if len(lessons) < max(1, min_lessons):
        raise ValueError(f"not enough confident lessons to forge a skill ({len(lessons)} found)")

    skill_name = _safe_name(name or topic or _topic_from_lessons([lesson.text for lesson in lessons]))
    target = root / ".crypt" / "skills" / skill_name / "SKILL.md"
    created = not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_skill_text(skill_name, lessons, topic=topic), encoding="utf-8")
    return ForgeResult(
        path=target,
        skill_name=skill_name,
        lesson_count=len(lessons),
        created=created,
    )


def format_result(result: ForgeResult) -> str:
    action = "created" if result.created else "updated"
    return f"{action} ${result.skill_name} from {result.lesson_count} lesson(s): {result.path}"


def _skill_text(skill_name: str, lessons: list[learning.Lesson], *, topic: str) -> str:
    description = (
        f"Learned Crypt workflow for {topic}."
        if topic
        else "Learned Crypt workflow promoted from repeated project lessons."
    )
    lines = [
        "---",
        f"name: {skill_name}",
        f"description: {description}",
        "---",
        "",
        f"# {skill_name}",
        "",
        "Use this skill when the user's request matches these learned project patterns.",
        "",
        "## Learned Operating Rules",
        "",
    ]
    for lesson in lessons[:12]:
        tags = f" ({', '.join(lesson.tags[:4])})" if lesson.tags else ""
        lines.append(f"- {redact.text(lesson.text)}{tags}")
    lines.extend(
        [
            "",
            "## Verification",
            "",
            "- Prefer lessons that mention explicit verification commands.",
            "- If a lesson conflicts with current repository files or user instructions, follow the current evidence.",
            "",
            f"_Forged by Crypt on {time.strftime('%Y-%m-%d')}._",
            "",
        ]
    )
    return "\n".join(lines)


def _topic_from_lessons(texts: list[str]) -> str:
    counts: dict[str, int] = {}
    for text in texts:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{4,}", text.lower()):
            if token in {"crypt", "reflection", "project", "successful", "similar", "verified"}:
                continue
            counts[token] = counts.get(token, 0) + 1
    if not counts:
        return "learned-workflow"
    return max(counts.items(), key=lambda item: item[1])[0]


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value or "").strip().lower()).strip("-")
    return clean or "learned-workflow"
