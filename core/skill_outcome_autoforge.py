"""Create skills from repeated successful task outcomes."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import learning, skill_forge, skills


@dataclass(frozen=True)
class OutcomeSkillCandidate:
    topic: str
    episode_count: int
    lesson_count: int
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutcomeAutoforgeResult:
    candidates: list[OutcomeSkillCandidate]
    forged: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "forged": self.forged,
            "skipped": self.skipped,
        }


def find_candidates(cwd: str | Path, *, min_episodes: int = 3) -> list[OutcomeSkillCandidate]:
    episodes = [
        episode for episode in learning.list_episodes(cwd, limit=200)
        if str(episode.status or "").lower() == "completed"
    ]
    grouped: dict[str, list[learning.Episode]] = {}
    for episode in episodes:
        topic = _topic(episode)
        grouped.setdefault(topic, []).append(episode)
    candidates: list[OutcomeSkillCandidate] = []
    for topic, rows in grouped.items():
        if len(rows) < min_episodes:
            continue
        lessons = learning.search_lessons(cwd, topic.replace("-", " "), limit=20)
        lesson_count = len([lesson for lesson in lessons if lesson.confidence >= 0.5])
        changed_paths = _dedupe([path for episode in rows for path in episode.changed_paths])[:8]
        verification_count = sum(1 for episode in rows if episode.verification_commands)
        tool_count = len(_dedupe([tool for episode in rows for tool in episode.tools]))
        confidence = min(
            0.98,
            0.34
            + min(len(rows), 6) * 0.08
            + min(lesson_count, 5) * 0.07
            + min(verification_count, 4) * 0.05
            + min(len(changed_paths), 5) * 0.02
            + min(tool_count, 4) * 0.02,
        )
        reasons = [
            f"{len(rows)} successful episode(s)",
            f"{lesson_count} matching lesson(s)",
        ]
        if verification_count:
            reasons.append(f"{verification_count} verified episode(s)")
        if changed_paths:
            reasons.append(f"{len(changed_paths)} changed area(s)")
        candidates.append(
            OutcomeSkillCandidate(
                topic=topic,
                episode_count=len(rows),
                lesson_count=lesson_count,
                confidence=round(confidence, 2),
                reasons=reasons,
                prompts=[episode.prompt for episode in rows[:5]],
                changed_paths=changed_paths,
            )
        )
    candidates.sort(key=lambda item: (item.confidence, item.episode_count, item.lesson_count), reverse=True)
    return candidates


def autoforge(
    cwd: str | Path,
    *,
    min_episodes: int = 3,
    min_lessons: int = 2,
    max_skills: int = 2,
    force: bool = False,
) -> OutcomeAutoforgeResult:
    candidates = find_candidates(cwd, min_episodes=min_episodes)
    existing = {skill.name for skill in skills.discover(cwd, include_disabled=True)}
    forged: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for candidate in candidates:
        if len(forged) >= max_skills:
            break
        if candidate.topic in existing:
            skipped.append({"topic": candidate.topic, "reason": "skill already exists"})
            continue
        if not force and candidate.lesson_count < max(1, min_lessons):
            skipped.append({"topic": candidate.topic, "reason": "not enough matching lessons"})
            continue
        if not force and candidate.confidence < 0.58:
            skipped.append({"topic": candidate.topic, "reason": "confidence below threshold"})
            continue
        try:
            result = skill_forge.forge_skill(cwd, topic=candidate.topic, min_lessons=max(1, min_lessons))
        except Exception as exc:
            skipped.append({"topic": candidate.topic, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        forged.append(
            {
                "topic": candidate.topic,
                "skill": result.skill_name,
                "path": str(result.path),
                "created": result.created,
                "validated": result.validated,
                "qualityScore": result.quality_score,
                "qualityStatus": result.quality_status,
                "lessonCount": result.lesson_count,
                "confidence": candidate.confidence,
            }
        )
    return OutcomeAutoforgeResult(candidates=candidates, forged=forged, skipped=skipped)


def snapshot(cwd: str | Path) -> dict[str, Any]:
    candidates = find_candidates(cwd, min_episodes=2)
    return OutcomeAutoforgeResult(candidates=candidates).to_dict()


def prompt_section(cwd: str | Path) -> str:
    candidates = find_candidates(cwd, min_episodes=2)
    if not candidates:
        return ""
    lines = ["# Outcome Skill Autoforge"]
    for candidate in candidates[:5]:
        lines.append(
            f"- {candidate.topic}: {candidate.episode_count} successful episode(s), "
            f"{candidate.lesson_count} lesson(s), confidence {candidate.confidence:.2f}; "
            "promote to SKILL.md when the pattern repeats."
        )
    return "\n".join(lines)


def _topic(episode: learning.Episode) -> str:
    haystack = " ".join([episode.prompt, " ".join(episode.changed_paths), " ".join(episode.tools)]).lower()
    if any(term in haystack for term in ("frontend", "webui", "ui", ".css", ".html", ".tsx", ".jsx")):
        return "frontend-workflow"
    if any(term in haystack for term in ("release", "verify", "checklist", "push")):
        return "release-workflow"
    if any(term in haystack for term in ("business", "revenue", "customer", "lead")):
        return "business-ops"
    if any(term in haystack for term in ("research", "source", "citation", "lookup")):
        return "research-workflow"
    if any(term in haystack for term in ("voice", "tts", "mic", "kokoro")):
        return "voice-workflow"
    if any(term in haystack for term in ("memory", "persona", "soul")):
        return "memory-workflow"
    tokens = [
        token
        for token in re.findall(r"[a-z][a-z0-9_-]{4,}", haystack)
        if token not in {"crypt", "update", "build", "fixed", "tests", "core"}
    ]
    return tokens[0] + "-workflow" if tokens else "general-workflow"


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(str(value or "").split())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out
