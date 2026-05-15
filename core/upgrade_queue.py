"""Self-upgrade idea queue for Crypt."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import goals, learning, memory_journal, reflection, session, settings, work_threads


SCHEMA_VERSION = 1
STATUSES = {"proposed", "accepted", "mission", "dismissed", "done"}


@dataclass(frozen=True)
class UpgradeIdea:
    idea_id: str
    title: str
    rationale: str
    source: str = "runtime"
    score: float = 0.5
    status: str = "proposed"
    tags: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    mission_id: str = ""
    created_at: int = 0
    updated_at: int = 0


def queue_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "upgrades" / "upgrade_queue.json"


def suggest(cwd: str | Path, *, limit: int = 20) -> list[UpgradeIdea]:
    """Collect upgrade ideas from corrections, failures, reflections, and open loops."""
    root = Path(cwd).expanduser().resolve()
    existing = {idea.idea_id: idea for idea in list_ideas(root, include_all=True)}
    changed = False
    for candidate in _candidates(root):
        idea = _upsert_candidate(existing, candidate)
        changed = True
        existing[idea.idea_id] = idea
    ideas = sorted(existing.values(), key=lambda item: (item.status == "proposed", item.score, item.updated_at), reverse=True)
    if changed:
        _write(root, ideas)
    return [idea for idea in ideas if idea.status == "proposed"][: max(1, limit)]


def list_ideas(cwd: str | Path, *, include_all: bool = False, limit: int = 100) -> list[UpgradeIdea]:
    ideas = _read(cwd)
    if not include_all:
        ideas = [idea for idea in ideas if idea.status == "proposed"]
    ideas.sort(key=lambda item: (item.score, item.updated_at), reverse=True)
    return ideas[: max(1, limit)]


def update_status(cwd: str | Path, idea_id: str, status: str) -> UpgradeIdea:
    clean_status = str(status or "").strip().lower()
    if clean_status not in STATUSES:
        raise ValueError(f"unknown upgrade idea status: {status}")
    ideas = _read(cwd)
    out: list[UpgradeIdea] = []
    updated: UpgradeIdea | None = None
    now = _now()
    for idea in ideas:
        if idea.idea_id == idea_id:
            data = asdict(idea)
            data["status"] = clean_status
            data["updated_at"] = now
            updated = UpgradeIdea(**data)
            out.append(updated)
        else:
            out.append(idea)
    if updated is None:
        raise KeyError(f"upgrade idea not found: {idea_id}")
    _write(cwd, out)
    return updated


def convert_to_mission(cwd: str | Path, idea_id: str) -> tuple[UpgradeIdea, goals.Goal, work_threads.WorkThread]:
    root = Path(cwd).expanduser().resolve()
    ideas = _read(root)
    idea = next((item for item in ideas if item.idea_id == idea_id), None)
    if idea is None:
        raise KeyError(f"upgrade idea not found: {idea_id}")
    goal = goals.add_goal(
        "Upgrade Crypt: " + idea.title,
        description=idea.rationale + _signal_text(idea.signals),
        workspace=root,
        success_metric="Upgrade is implemented, tested, and documented.",
        priority=2,
        tags=["self-upgrade", *idea.tags[:5]],
    )
    thread = work_threads.ensure_for_goal(goal, prompt_text=idea.rationale, source="upgrade-queue")
    updated = _replace(
        root,
        idea_id,
        status="mission",
        mission_id=goal.goal_id,
        signals=[goal.goal_id, *idea.signals],
    )
    return updated, goal, thread


def snapshot(cwd: str | Path, *, limit: int = 8) -> dict[str, Any]:
    proposed = list_ideas(cwd, limit=limit)
    all_ideas = list_ideas(cwd, include_all=True, limit=250)
    counts: dict[str, int] = {}
    for idea in all_ideas:
        counts[idea.status] = counts.get(idea.status, 0) + 1
    return {
        "path": str(queue_path(cwd)),
        "count": len(all_ideas),
        "statusCounts": counts,
        "proposed": [asdict(idea) for idea in proposed],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    ideas = list_ideas(cwd, limit=limit)
    if not ideas:
        return ""
    lines = ["# Self-Upgrade Queue"]
    for idea in ideas:
        lines.append(f"- {idea.score:.2f} {idea.title}: {idea.rationale}")
    return "\n".join(lines)


def _candidates(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lesson in learning.list_lessons(root)[:80]:
        tag_set = {tag.lower() for tag in lesson.tags}
        if "user-correction" in tag_set:
            out.append(
                {
                    "title": "Fix user-corrected behavior: " + _short(_strip_prefix(lesson.text, "User correction:"), 86),
                    "rationale": "The user explicitly corrected Crypt. Turn that feedback into a runtime/UI behavior improvement.",
                    "source": "user-correction",
                    "score": 0.9,
                    "tags": ["feedback", "user-correction"],
                    "signals": [lesson.lesson_id, lesson.text],
                }
            )
        if {"failure", "recovery", "tool-recovery"} & tag_set:
            out.append(
                {
                    "title": "Harden recovery path: " + _short(lesson.text, 82),
                    "rationale": "A failed or recovered task produced a reusable weakness. Reduce the chance it repeats.",
                    "source": "outcome-learning",
                    "score": 0.82,
                    "tags": ["recovery", "failure"],
                    "signals": [lesson.lesson_id, lesson.text],
                }
            )
    for item in reflection.list_reflections(root, limit=40):
        if item.failed or item.next_actions:
            out.append(
                {
                    "title": "Improve reflected workflow: " + _short(item.summary, 90),
                    "rationale": "Reflection found failed evidence or a next-time action.",
                    "source": "reflection",
                    "score": 0.74,
                    "tags": ["reflection", "workflow"],
                    "signals": [item.reflection_id, *item.failed[:2], *item.next_actions[:2]],
                }
            )
    for item in memory_journal.filter_signals(root, memory_type="open-loop")[:40]:
        text = str(item.get("text") or "")
        if re.search(r"\b(fix|improve|upgrade|better|rework|should)\b", text, re.I):
            out.append(
                {
                    "title": "Address remembered improvement: " + _short(text, 90),
                    "rationale": "Memory contains an open loop that looks like a Crypt improvement request.",
                    "source": "memory",
                    "score": 0.68,
                    "tags": ["memory", "open-loop"],
                    "signals": [str(item.get("signal_id") or ""), text],
                }
            )
    return out


def _upsert_candidate(existing: dict[str, UpgradeIdea], candidate: dict[str, Any]) -> UpgradeIdea:
    title = _clean(candidate.get("title", ""), 140)
    rationale = _clean(candidate.get("rationale", ""), 500)
    idea_id = _idea_id(title)
    now = _now()
    current = existing.get(idea_id)
    if current:
        data = asdict(current)
        data["score"] = min(1.0, max(float(data.get("score") or 0.0), float(candidate.get("score") or 0.5)) + 0.03)
        data["signals"] = _dedupe([*current.signals, *candidate.get("signals", [])])[:12]
        data["tags"] = _dedupe([*current.tags, *candidate.get("tags", [])])
        data["updated_at"] = now
        return UpgradeIdea(**data)
    return UpgradeIdea(
        idea_id=idea_id,
        title=title,
        rationale=rationale,
        source=_clean(candidate.get("source", "runtime"), 80),
        score=max(0.0, min(1.0, float(candidate.get("score") or 0.5))),
        status="proposed",
        tags=_dedupe([str(tag) for tag in candidate.get("tags", [])]),
        signals=_dedupe([str(signal) for signal in candidate.get("signals", [])])[:12],
        created_at=now,
        updated_at=now,
    )


def _replace(cwd: str | Path, idea_id: str, **values: Any) -> UpgradeIdea:
    ideas = _read(cwd)
    out: list[UpgradeIdea] = []
    updated: UpgradeIdea | None = None
    now = _now()
    for idea in ideas:
        if idea.idea_id != idea_id:
            out.append(idea)
            continue
        data = asdict(idea)
        for key, value in values.items():
            if key == "signals":
                data[key] = _dedupe([str(item) for item in value])[:12]
            elif key in data:
                data[key] = value
        data["updated_at"] = now
        updated = UpgradeIdea(**data)
        out.append(updated)
    if updated is None:
        raise KeyError(f"upgrade idea not found: {idea_id}")
    _write(cwd, out)
    return updated


def _read(cwd: str | Path) -> list[UpgradeIdea]:
    path = queue_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[UpgradeIdea] = []
    for item in data.get("ideas", []):
        if not isinstance(item, dict):
            continue
        try:
            status = str(item.get("status") or "proposed")
            if status not in STATUSES:
                status = "proposed"
            out.append(
                UpgradeIdea(
                    idea_id=str(item.get("idea_id") or ""),
                    title=str(item.get("title") or ""),
                    rationale=str(item.get("rationale") or ""),
                    source=str(item.get("source") or "runtime"),
                    score=float(item.get("score") or 0.5),
                    status=status,
                    tags=[str(tag) for tag in item.get("tags", []) if str(tag)],
                    signals=[str(signal) for signal in item.get("signals", []) if str(signal)],
                    mission_id=str(item.get("mission_id") or ""),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [idea for idea in out if idea.idea_id and idea.title]


def _write(cwd: str | Path, ideas: list[UpgradeIdea]) -> None:
    path = queue_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "ideas": [asdict(idea) for idea in ideas[:250]]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _idea_id(title: str) -> str:
    return "upg_" + hashlib.sha1(_normalize(title).encode("utf-8", errors="replace")).hexdigest()[:14]


def _signal_text(signals: list[str]) -> str:
    useful = [signal for signal in signals if signal and not signal.startswith(("learn_", "reflect_", "goal_"))]
    return ("\n\nSignals:\n- " + "\n- ".join(useful[:6])) if useful else ""


def _strip_prefix(text: str, prefix: str) -> str:
    return text[len(prefix):].strip() if str(text).startswith(prefix) else str(text)


def _short(text: str, limit: int) -> str:
    clean = _clean(text, limit)
    return clean or "unnamed improvement"


def _clean(value: object, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = _clean(item, 500)
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _now() -> int:
    return int(time.time())
