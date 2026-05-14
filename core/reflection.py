"""Post-task reflection for Crypt's learning loop."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import learning, redact, settings


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Reflection:
    reflection_id: str
    episode_id: str
    task_id: str
    project: str
    summary: str
    worked: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    lesson_ids: list[str] = field(default_factory=list)
    confidence: float = 0.5
    created_at: int = 0


def reflections_path() -> Path:
    return learning.learning_dir() / "reflections.jsonl"


def reflect_episode(cwd: str | Path, episode: learning.Episode) -> Reflection:
    worked: list[str] = []
    failed: list[str] = []
    next_actions: list[str] = []

    if episode.verification_commands:
        worked.append("Verification was grounded in: " + "; ".join(episode.verification_commands[:3]))
    else:
        next_actions.append("Run or document a targeted verification command before claiming completion.")

    if episode.changed_paths:
        worked.append("Useful code areas were: " + ", ".join(_top_areas(episode.changed_paths)[:5]))

    failed_evidence = [item for item in episode.evidence if item.get("ok") is False]
    for item in failed_evidence[:4]:
        source = item.get("tool") or item.get("source") or "tool"
        output = str(item.get("output_head") or item.get("summary") or "")
        failed.append(f"{source}: {_one_line(output, 180)}")
        hint = _recovery_hint(output)
        if hint:
            next_actions.append(hint)

    if episode.status != "completed":
        failed.append(f"Task ended with status: {episode.status}")
        next_actions.append("Re-open the task from its event log before retrying so the next attempt starts from evidence.")

    if not worked and not failed:
        worked.append("Task produced an episode but no tool evidence was recorded.")

    lesson_ids: list[str] = []
    for text, tags, confidence in _lesson_candidates(episode, worked, failed, next_actions):
        lesson = learning.add_lesson(
            text,
            cwd=cwd,
            scope="project",
            tags=tags,
            source="reflection",
            source_task_id=episode.task_id,
            confidence=confidence,
        )
        lesson_ids.append(lesson.lesson_id)

    reflection = Reflection(
        reflection_id=learning._new_id("reflect", episode.episode_id),  # noqa: SLF001 - shared local id helper
        episode_id=episode.episode_id,
        task_id=episode.task_id,
        project=episode.project,
        summary=_summary(episode, worked, failed, next_actions),
        worked=_dedupe(worked),
        failed=_dedupe(failed),
        next_actions=_dedupe(next_actions),
        lesson_ids=_dedupe(lesson_ids),
        confidence=_confidence(episode, worked, failed),
        created_at=int(time.time()),
    )
    _append(reflection)
    return reflection


def reflect_recent(cwd: str | Path, *, limit: int = 5) -> list[Reflection]:
    existing = {item.episode_id for item in list_reflections(cwd, limit=500)}
    reflections: list[Reflection] = []
    for episode in learning.list_episodes(cwd, limit=limit):
        if episode.episode_id in existing:
            continue
        reflections.append(reflect_episode(cwd, episode))
    return reflections


def list_reflections(cwd: str | Path | None = None, *, limit: int = 12) -> list[Reflection]:
    project = learning._project_key(cwd) if cwd is not None else None  # noqa: SLF001 - same storage namespace
    out = []
    for item in _read_jsonl(reflections_path()):
        if item.get("type") != "reflection":
            continue
        try:
            reflection = Reflection(
                reflection_id=str(item.get("reflection_id") or ""),
                episode_id=str(item.get("episode_id") or ""),
                task_id=str(item.get("task_id") or ""),
                project=str(item.get("project") or ""),
                summary=str(item.get("summary") or ""),
                worked=[str(value) for value in item.get("worked", [])],
                failed=[str(value) for value in item.get("failed", [])],
                next_actions=[str(value) for value in item.get("next_actions", [])],
                lesson_ids=[str(value) for value in item.get("lesson_ids", [])],
                confidence=float(item.get("confidence") or 0.5),
                created_at=int(item.get("created_at") or 0),
            )
        except Exception:
            continue
        if not reflection.reflection_id:
            continue
        if project is None or reflection.project == project:
            out.append(reflection)
    out.sort(key=lambda value: value.created_at, reverse=True)
    return out[: max(1, limit)]


def format_reflections(cwd: str | Path, *, limit: int = 12) -> str:
    reflections = list_reflections(cwd, limit=limit)
    if not reflections:
        return "no reflections found"
    lines: list[str] = []
    for item in reflections:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.created_at))
        lines.append(f"{item.reflection_id} {item.confidence:.2f} {when} - {item.summary}")
        for action in item.next_actions[:3]:
            lines.append(f"  next: {action}")
    return "\n".join(lines)


def prompt_section(cwd: str | Path, *, limit: int = 4) -> str:
    reflections = list_reflections(cwd, limit=limit)
    if not reflections:
        return ""
    lines = ["# Recent Reflections"]
    for item in reflections:
        lines.append(f"- {item.summary}")
        for action in item.next_actions[:2]:
            lines.append(f"  - Next time: {action}")
    return "\n".join(lines)


def _lesson_candidates(
    episode: learning.Episode,
    worked: list[str],
    failed: list[str],
    next_actions: list[str],
) -> list[tuple[str, list[str], float]]:
    candidates: list[tuple[str, list[str], float]] = []
    if episode.status == "completed" and episode.verification_commands:
        candidates.append((
            "Reflection: this task type should be closed with verification command(s): "
            + "; ".join(episode.verification_commands[:3]),
            ["reflection", "verification"],
            0.76,
        ))
    if failed and next_actions:
        candidates.append((
            "Reflection recovery pattern: " + next_actions[0],
            ["reflection", "recovery"],
            0.64,
        ))
    if episode.changed_paths:
        candidates.append((
            "Reflection navigation hint: inspect "
            + ", ".join(_top_areas(episode.changed_paths)[:4])
            + " for similar work.",
            ["reflection", "navigation"],
            0.6,
        ))
    if worked and not failed:
        candidates.append((
            "Reflection: repeat the successful pattern: " + worked[0],
            ["reflection", "success"],
            0.58,
        ))
    return candidates


def _summary(
    episode: learning.Episode,
    worked: list[str],
    failed: list[str],
    next_actions: list[str],
) -> str:
    status = episode.status
    prompt = _one_line(episode.prompt, 90)
    if failed:
        return f"{status}: {prompt}; learn from {len(failed)} issue(s)"
    if next_actions:
        return f"{status}: {prompt}; next action: {_one_line(next_actions[0], 80)}"
    if worked:
        return f"{status}: {prompt}; worked: {_one_line(worked[0], 90)}"
    return f"{status}: {prompt}"


def _confidence(episode: learning.Episode, worked: list[str], failed: list[str]) -> float:
    score = 0.45
    if episode.status == "completed":
        score += 0.2
    if episode.verification_commands:
        score += 0.2
    if worked:
        score += 0.1
    if failed:
        score -= 0.1
    return max(0.1, min(1.0, score))


def _append(reflection: Reflection) -> None:
    path = reflections_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"schema": SCHEMA_VERSION, "type": "reflection", **asdict(reflection)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
    settings.restrict_file_permissions(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
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


def _top_areas(paths: list[str]) -> list[str]:
    out = []
    for path in paths:
        parts = str(path).replace("\\", "/").strip("/").split("/")
        out.append(parts[0] if len(parts) > 1 else parts[0])
    return _dedupe(out)


def _recovery_hint(text: str) -> str:
    marker = "Recovery:"
    if marker not in text:
        return ""
    return _one_line(text.split(marker, 1)[1].strip(), 220)


def _one_line(text: str, limit: int) -> str:
    clean = " ".join(redact.text(str(text or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        clean = str(item or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out
