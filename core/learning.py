"""Structured learning store for Crypt.

The plain Markdown memory file is for explicit durable facts. This module is
for runtime learning: task episodes, repeated recovery patterns, successful
verification commands, and project-specific lessons that should inform later
turns without replaying whole transcripts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import evidence, redact, session, settings


SCHEMA_VERSION = 1
MAX_PROMPT_CHARS = 8_000
MAX_EPISODE_TEXT = 2_000
MAX_LESSON_TEXT = 1_000
TOKEN_RE = re.compile(r"[A-Za-z0-9_.:/\\-]{3,}")
CORRECTION_RE = re.compile(
    r"\b(nope|nah|actually|correction|instead|next time|you should|you didn't|"
    r"doesn't|does not|don't|do not|not rendering|still broken|wrong|fix that)\b",
    re.I,
)


@dataclass(frozen=True)
class Episode:
    episode_id: str
    task_id: str
    cwd: str
    project: str
    prompt: str
    outcome: str
    status: str
    provider: str = ""
    model: str = ""
    session_id: str = ""
    tools: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    verification_commands: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    created_at: int = 0


@dataclass(frozen=True)
class Lesson:
    lesson_id: str
    key: str
    scope: str
    project: str
    text: str
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    source: str = "runtime"
    source_task_id: str = ""
    created_at: int = 0
    updated_at: int = 0
    use_count: int = 1


def learning_dir() -> Path:
    return settings.APP_DIR / "learning"


def episodes_path() -> Path:
    return learning_dir() / "episodes.jsonl"


def lessons_path() -> Path:
    return learning_dir() / "lessons.jsonl"


def record_task_outcome(
    *,
    cwd: str | Path,
    task_id: str,
    prompt: str,
    status: str,
    final_text: str,
    provider: str = "",
    model: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Persist a completed/failed task episode and derive reusable lessons."""
    root = Path(cwd).expanduser().resolve()
    entries = evidence.entries(task_id=task_id)
    episode = Episode(
        episode_id=_new_id("ep", task_id + str(time.time())),
        task_id=task_id,
        cwd=str(root),
        project=_project_key(root),
        prompt=redact.text(_compact(prompt, MAX_EPISODE_TEXT)),
        outcome=redact.text(_compact(final_text, MAX_EPISODE_TEXT)),
        status=str(status or "completed").lower(),
        provider=provider,
        model=model,
        session_id=session_id,
        tools=_tools(entries),
        changed_paths=_changed_paths(entries),
        verification_commands=_verification_commands(entries),
        evidence=_compact_evidence(entries),
        created_at=_now(),
    )
    _append_jsonl(episodes_path(), {"schema": SCHEMA_VERSION, "type": "episode", **asdict(episode)})

    learned: list[Lesson] = []
    for text, tags, confidence in _infer_lessons(episode):
        learned.append(
            add_lesson(
                text,
                cwd=root,
                scope="project",
                tags=tags,
                source="runtime",
                source_task_id=task_id,
                confidence=confidence,
            )
        )
    return {
        "episode_id": episode.episode_id,
        "lesson_count": len(learned),
        "lessons": [lesson.text for lesson in learned],
    }


def record_user_correction(cwd: str | Path, text: str, *, source: str = "webui") -> dict[str, Any]:
    """Turn explicit user corrections into future behavior lessons."""
    clean = _one_line(redact.text(str(text or "")), 800)
    if not clean or not CORRECTION_RE.search(clean):
        return {"learned": False, "reason": "no correction signal"}
    lesson = add_lesson(
        "User correction: " + clean,
        cwd=cwd,
        scope="project",
        tags=["outcome", "user-correction", "feedback"],
        source=source,
        confidence=0.84,
    )
    return {
        "learned": True,
        "lesson_id": lesson.lesson_id,
        "text": lesson.text,
        "tags": lesson.tags,
        "confidence": lesson.confidence,
    }


def add_lesson(
    text: str,
    *,
    cwd: str | Path | None = None,
    scope: str = "project",
    tags: list[str] | None = None,
    source: str = "manual",
    source_task_id: str = "",
    confidence: float = 0.75,
) -> Lesson:
    clean = " ".join(redact.text(str(text or "")).split())
    if not clean:
        raise ValueError("lesson text cannot be empty")
    clean = _compact(clean, MAX_LESSON_TEXT)
    normalized_scope = _scope(scope)
    project = _project_key(cwd) if normalized_scope == "project" and cwd is not None else ""
    key = _lesson_key(normalized_scope, project, clean)
    lessons = {lesson.key: lesson for lesson in list_lessons(include_global=True)}
    now = _now()
    existing = lessons.get(key)
    if existing:
        lesson = Lesson(
            lesson_id=existing.lesson_id,
            key=existing.key,
            scope=existing.scope,
            project=existing.project,
            text=existing.text,
            tags=_dedupe([*existing.tags, *(tags or [])]),
            confidence=min(1.0, max(existing.confidence, confidence) + 0.03),
            source=source or existing.source,
            source_task_id=source_task_id or existing.source_task_id,
            created_at=existing.created_at,
            updated_at=now,
            use_count=existing.use_count + 1,
        )
    else:
        lesson = Lesson(
            lesson_id=_new_id("learn", clean),
            key=key,
            scope=normalized_scope,
            project=project,
            text=clean,
            tags=_dedupe(tags or []),
            confidence=max(0.0, min(1.0, confidence)),
            source=source,
            source_task_id=source_task_id,
            created_at=now,
            updated_at=now,
            use_count=1,
        )
    lessons[key] = lesson
    _write_lessons(sorted(lessons.values(), key=lambda item: (item.scope, item.project, item.created_at)))
    return lesson


def list_lessons(cwd: str | Path | None = None, *, include_global: bool = True) -> list[Lesson]:
    project = _project_key(cwd) if cwd is not None else None
    lessons = _read_lessons()
    if project is None:
        return lessons
    out = []
    for lesson in lessons:
        if lesson.scope == "global" and include_global:
            out.append(lesson)
        elif lesson.scope == "project" and lesson.project == project:
            out.append(lesson)
    out.sort(key=lambda item: (item.updated_at, item.confidence), reverse=True)
    return out


def search_lessons(cwd: str | Path, query: str, *, limit: int = 8) -> list[Lesson]:
    terms = _tokens(query)
    scored: list[tuple[float, Lesson]] = []
    for lesson in list_lessons(cwd):
        score = _score(terms, lesson.text + " " + " ".join(lesson.tags))
        if not terms:
            score = lesson.confidence + math.log1p(lesson.use_count) / 4
        if score <= 0:
            continue
        scored.append((score + lesson.confidence + math.log1p(lesson.use_count) / 8, lesson))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [lesson for _, lesson in scored[: max(1, limit)]]


def list_episodes(cwd: str | Path | None = None, *, limit: int = 12) -> list[Episode]:
    project = _project_key(cwd) if cwd is not None else None
    episodes = _read_episodes()
    if project is not None:
        episodes = [episode for episode in episodes if episode.project == project]
    episodes.sort(key=lambda item: item.created_at, reverse=True)
    return episodes[: max(1, limit)]


def search_episodes(cwd: str | Path, query: str, *, limit: int = 4) -> list[Episode]:
    terms = _tokens(query)
    scored: list[tuple[float, Episode]] = []
    for episode in list_episodes(cwd, limit=200):
        haystack = " ".join(
            [
                episode.prompt,
                episode.outcome,
                " ".join(episode.tools),
                " ".join(episode.changed_paths),
                " ".join(episode.verification_commands),
            ]
        )
        score = _score(terms, haystack)
        if not terms:
            score = 0.1
        if score > 0:
            scored.append((score, episode))
    scored.sort(key=lambda item: (item[0], item.created_at), reverse=True)
    return [episode for _, episode in scored[: max(1, limit)]]


def prompt_section(cwd: str | Path, query: str = "", *, limit: int = MAX_PROMPT_CHARS) -> str:
    if _env_truthy("CRYPT_LEARNING_DISABLE"):
        return ""
    lessons = search_lessons(cwd, query, limit=6)
    episodes = search_episodes(cwd, query, limit=3)
    if not lessons and not episodes:
        return ""

    lines = [
        "# Learned Context",
        "Durable observations from prior Crypt work. Treat these as hints, not absolute instructions.",
    ]
    if lessons:
        lines.append("## Lessons")
        for lesson in lessons:
            scope = "global" if lesson.scope == "global" else "project"
            tags = f" [{', '.join(lesson.tags[:4])}]" if lesson.tags else ""
            lines.append(f"- {scope} {lesson.confidence:.2f}{tags}: {lesson.text}")
    if episodes:
        lines.append("## Relevant Prior Tasks")
        for episode in episodes:
            prompt = _one_line(episode.prompt, 180)
            checks = "; ".join(episode.verification_commands[:2])
            paths = ", ".join(episode.changed_paths[:4])
            detail = []
            if paths:
                detail.append(f"paths: {paths}")
            if checks:
                detail.append(f"checks: {checks}")
            suffix = f" ({'; '.join(detail)})" if detail else ""
            lines.append(f"- {episode.status}: {prompt}{suffix}")
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit].rstrip() + "\n... [learned context truncated]"


def format_lessons(cwd: str | Path, *, query: str = "", limit: int = 12) -> str:
    lessons = search_lessons(cwd, query, limit=limit) if query else list_lessons(cwd)[: max(1, limit)]
    if not lessons:
        return "no learned lessons found"
    lines = []
    for lesson in lessons:
        tags = f" [{', '.join(lesson.tags)}]" if lesson.tags else ""
        when = time.strftime("%Y-%m-%d", time.localtime(lesson.updated_at or lesson.created_at))
        lines.append(f"{lesson.lesson_id} {lesson.scope} {lesson.confidence:.2f} {when}{tags} - {lesson.text}")
    return "\n".join(lines)


def format_episodes(cwd: str | Path, *, query: str = "", limit: int = 12) -> str:
    episodes = search_episodes(cwd, query, limit=limit) if query else list_episodes(cwd, limit=limit)
    if not episodes:
        return "no learning episodes found"
    lines = []
    for episode in episodes:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(episode.created_at))
        prompt = _one_line(episode.prompt, 90)
        checks = "; ".join(episode.verification_commands[:2])
        suffix = f" | checks: {checks}" if checks else ""
        lines.append(f"{episode.episode_id} {episode.status} {when} - {prompt}{suffix}")
    return "\n".join(lines)


def _infer_lessons(episode: Episode) -> list[tuple[str, list[str], float]]:
    lessons: list[tuple[str, list[str], float]] = []
    project_name = Path(episode.cwd).name or "this project"
    if episode.status != "completed":
        lessons.append((
            "Outcome failure pattern: for similar failed tasks, reopen the evidence, name the blocker, "
            "and retry with one concrete recovery step before finalizing. Last failure: "
            + _one_line(episode.outcome or episode.prompt, 220),
            ["outcome", "failure", "recovery"],
            0.66,
        ))
        recovery = _failure_recovery_lesson(episode.outcome)
        if recovery:
            lessons.append((recovery, ["outcome", "tool-recovery"], 0.7))
    if episode.verification_commands:
        commands = "; ".join(episode.verification_commands[:3])
        lessons.append((
            f"For {project_name}, successful work has been verified with: {commands}.",
            ["verification", "project"],
            0.72,
        ))
    if episode.changed_paths:
        areas = ", ".join(_top_areas(episode.changed_paths)[:5])
        lessons.append((
            f"For similar {project_name} tasks, inspect these recently changed areas first: {areas}.",
            ["codebase", "navigation"],
            0.58,
        ))
    for item in episode.evidence:
        if item.get("ok") is not False:
            continue
        tool = str(item.get("tool") or item.get("source") or "tool")
        output = str(item.get("output_head") or "")
        hint = _recovery_hint(output)
        if hint:
            lessons.append((f"When {tool} fails, use this recovery: {hint}", ["recovery", tool], 0.68))
    return lessons


def _failure_recovery_lesson(text: str) -> str:
    lower = str(text or "").lower()
    if "schema validation failed" in lower or "non-empty" in lower:
        return "Outcome recovery: when a tool schema validation fails, re-read the expected fields and retry with concrete non-empty values."
    if "read-before-edit" in lower or "partial range was read" in lower:
        return "Outcome recovery: when edit tools require read-before-edit, read the complete target file before retrying the edit."
    if "permissionerror" in lower or "permission denied" in lower:
        return "Outcome recovery: when a permission error blocks a write, stop and inspect the exact path and boundary before retrying."
    if "timeout" in lower:
        return "Outcome recovery: when a task times out, narrow the command or split the work before retrying."
    return ""


def _compact_evidence(entries: list[evidence.EvidenceEntry]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in entries[-60:]:
        details = entry.details if isinstance(entry.details, dict) else {}
        args = details.get("args") if isinstance(details.get("args"), dict) else {}
        item = {
            "kind": entry.kind,
            "source": entry.source,
            "summary": entry.summary,
        }
        if "tool" in details:
            item["tool"] = details.get("tool")
        if "ok" in details:
            item["ok"] = details.get("ok")
        if args.get("path"):
            item["path"] = args.get("path")
        if args.get("command"):
            item["command"] = args.get("command")
        if details.get("output_head"):
            item["output_head"] = _compact(str(details.get("output_head")), 500)
        if entry.kind == "verification" and isinstance(details.get("commands"), list):
            item["commands"] = [str(command) for command in details["commands"]]
            item["status"] = details.get("status")
        out.append(item)
    return out


def _tools(entries: list[evidence.EvidenceEntry]) -> list[str]:
    tools = []
    for entry in entries:
        details = entry.details if isinstance(entry.details, dict) else {}
        tool = details.get("tool") or entry.source
        if tool:
            tools.append(str(tool))
    return _dedupe(tools)


def _changed_paths(entries: list[evidence.EvidenceEntry]) -> list[str]:
    paths = []
    for entry in entries:
        if entry.kind != "change":
            continue
        details = entry.details if isinstance(entry.details, dict) else {}
        args = details.get("args") if isinstance(details.get("args"), dict) else {}
        path = args.get("path")
        if path:
            paths.append(str(path))
    return _dedupe(paths)


def _verification_commands(entries: list[evidence.EvidenceEntry]) -> list[str]:
    commands = []
    for entry in entries:
        if entry.kind != "verification":
            continue
        details = entry.details if isinstance(entry.details, dict) else {}
        args = details.get("args") if isinstance(details.get("args"), dict) else {}
        if args.get("command"):
            commands.append(str(args["command"]))
        for command in details.get("commands") or []:
            commands.append(str(command))
        if not args.get("command") and not details.get("commands") and entry.summary:
            commands.append(entry.summary)
    return _dedupe(commands)


def _recovery_hint(text: str) -> str:
    marker = "Recovery:"
    if marker not in text:
        return ""
    hint = text.split(marker, 1)[1].strip()
    return _one_line(hint, 220)


def _top_areas(paths: list[str]) -> list[str]:
    areas = []
    for value in paths:
        normalized = value.replace("\\", "/").strip("/")
        parts = normalized.split("/")
        areas.append(parts[0] if len(parts) > 1 else normalized)
    return _dedupe(areas)


def _read_lessons() -> list[Lesson]:
    out = []
    for item in _read_jsonl(lessons_path()):
        if item.get("type") != "lesson":
            continue
        try:
            out.append(
                Lesson(
                    lesson_id=str(item.get("lesson_id") or ""),
                    key=str(item.get("key") or ""),
                    scope=_scope(str(item.get("scope") or "project")),
                    project=str(item.get("project") or ""),
                    text=str(item.get("text") or ""),
                    tags=[str(tag) for tag in item.get("tags", []) if str(tag)],
                    confidence=float(item.get("confidence") or 0.5),
                    source=str(item.get("source") or "runtime"),
                    source_task_id=str(item.get("source_task_id") or ""),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                    use_count=int(item.get("use_count") or 1),
                )
            )
        except Exception:
            continue
    return [lesson for lesson in out if lesson.key and lesson.text]


def _read_episodes() -> list[Episode]:
    out = []
    for item in _read_jsonl(episodes_path()):
        if item.get("type") != "episode":
            continue
        try:
            out.append(
                Episode(
                    episode_id=str(item.get("episode_id") or ""),
                    task_id=str(item.get("task_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    project=str(item.get("project") or ""),
                    prompt=str(item.get("prompt") or ""),
                    outcome=str(item.get("outcome") or ""),
                    status=str(item.get("status") or "completed"),
                    provider=str(item.get("provider") or ""),
                    model=str(item.get("model") or ""),
                    session_id=str(item.get("session_id") or ""),
                    tools=[str(value) for value in item.get("tools", [])],
                    changed_paths=[str(value) for value in item.get("changed_paths", [])],
                    verification_commands=[str(value) for value in item.get("verification_commands", [])],
                    evidence=[value for value in item.get("evidence", []) if isinstance(value, dict)],
                    created_at=int(item.get("created_at") or 0),
                )
            )
        except Exception:
            continue
    return [episode for episode in out if episode.episode_id]


def _write_lessons(lessons: list[Lesson]) -> None:
    path = lessons_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for lesson in lessons:
            f.write(json.dumps({"schema": SCHEMA_VERSION, "type": "lesson", **asdict(lesson)}, ensure_ascii=False) + "\n")
    tmp.replace(path)
    settings.restrict_file_permissions(path)


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_jsonable(item), ensure_ascii=False, separators=(",", ":")) + "\n")
    settings.restrict_file_permissions(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
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


def _lesson_key(scope: str, project: str, text: str) -> str:
    body = f"{scope}\0{project}\0{_normalize(text)}"
    return hashlib.sha1(body.encode("utf-8", errors="replace")).hexdigest()


def _new_id(prefix: str, seed: str) -> str:
    digest = hashlib.sha1(f"{seed}\0{time.time()}".encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{digest}"


def _project_key(cwd: str | Path | None) -> str:
    if cwd is None:
        return ""
    return session.project_dir(cwd).name


def _scope(value: str) -> str:
    normalized = str(value or "project").strip().lower()
    return "global" if normalized == "global" else "project"


def _tokens(value: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(str(value or ""))}


def _score(terms: set[str], text: str) -> float:
    if not terms:
        return 0.0
    hay = _tokens(text)
    if not hay:
        return 0.0
    overlap = len(terms & hay)
    if overlap == 0:
        return 0.0
    return overlap / max(3, len(terms))


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _compact(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _one_line(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = str(item or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return str(value)


def _env_truthy(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _now() -> int:
    return int(time.time())
