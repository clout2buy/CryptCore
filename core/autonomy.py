"""Safe autonomous learning cycle for Crypt.

Autonomy here means Crypt can continuously review its own work, update lessons,
track goals, and promote stable patterns into skills. It deliberately does not
spend money, contact external services, or mutate arbitrary user projects by
itself; those actions remain normal tool calls behind the existing permission
model.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import goals, learning, memory_condenser, mission_brain, monitors, reflection, scheduler, settings, skill_forge, skill_outcome_autoforge, soul, upgrade_queue, work_threads


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AutonomyCycle:
    cycle_id: str
    cwd: str
    created_at: int
    reflected: int = 0
    goal_reviews: int = 0
    mission_steps: int = 0
    scheduled_jobs: int = 0
    monitor_changes: int = 0
    memory_promotions: int = 0
    upgrade_ideas: int = 0
    forged_skills: list[str] = field(default_factory=list)
    lessons_added: int = 0
    notes: list[str] = field(default_factory=list)


def autonomy_dir() -> Path:
    return settings.APP_DIR / "autonomy"


def cycles_path() -> Path:
    return autonomy_dir() / "cycles.jsonl"


def run_cycle(
    cwd: str | Path,
    *,
    force_forge: bool = False,
    max_reflections: int = 5,
) -> AutonomyCycle:
    root = Path(cwd).expanduser().resolve()
    notes: list[str] = []
    lessons_before = len(learning.list_lessons(root))

    reflected = reflection.reflect_recent(root, limit=max_reflections)
    if reflected:
        notes.append(f"reflected on {len(reflected)} recent task episode(s)")

    goal_reviews = _review_goals(root, notes)
    mission_steps = mission_brain.review_workspace(root)
    for step in mission_steps[:4]:
        notes.append(f"mission brain selected {step.kind} for {step.thread_id}: {step.action}")
    thread_reviews = work_threads.review_due(root)
    for thread in thread_reviews:
        notes.append(f"reviewed work thread {thread.thread_id}: {thread.title}")
    scheduled = scheduler.run_due(root)
    for result in scheduled.results[:4]:
        notes.append(result)
    monitor_results = monitors.run_monitors(root)
    changed_monitors = [item for item in monitor_results if item.changed]
    for result in changed_monitors[:4]:
        notes.append(result.summary)
    condensed = memory_condenser.condense(root)
    if condensed.promoted or condensed.discarded:
        notes.append(f"condensed memory: promoted={condensed.promoted} discarded={condensed.discarded}")
    upgrades = upgrade_queue.suggest(root, limit=8)
    if upgrades:
        notes.append(f"queued {len(upgrades)} self-upgrade idea(s)")
    forged = _forge_from_repeated_lessons(root, notes, force=force_forge)
    outcome_forge = skill_outcome_autoforge.autoforge(
        root,
        min_episodes=2 if force_forge else 3,
        min_lessons=1 if force_forge else 2,
        force=force_forge,
    )
    for item in outcome_forge.forged:
        skill_name = str(item.get("skill") or item.get("topic") or "")
        if skill_name:
            forged.append(skill_name)
            notes.append(f"autoforged skill ${skill_name} from repeated successful {item.get('topic')} outcomes")
    for item in outcome_forge.skipped[:2]:
        notes.append(f"autoforge skipped {item.get('topic')}: {item.get('reason')}")
    soul_update = soul.evolve(root)
    if soul_update.changed:
        notes.append(f"evolved Crypt soul from {soul_update.preference_count} learned preference(s)")

    cycle = AutonomyCycle(
        cycle_id=learning._new_id("auto", str(root)),  # noqa: SLF001 - shared local id helper
        cwd=str(root),
        created_at=int(time.time()),
        reflected=len(reflected),
        goal_reviews=goal_reviews,
        mission_steps=len(mission_steps),
        scheduled_jobs=scheduled.ran,
        monitor_changes=len(changed_monitors),
        memory_promotions=condensed.promoted,
        upgrade_ideas=len(upgrades),
        forged_skills=forged,
        lessons_added=max(0, len(learning.list_lessons(root)) - lessons_before),
        notes=notes or ["no autonomous changes needed"],
    )
    _append(cycle)
    return cycle


def list_cycles(cwd: str | Path | None = None, *, limit: int = 12) -> list[AutonomyCycle]:
    root = str(Path(cwd).expanduser().resolve()) if cwd else ""
    out: list[AutonomyCycle] = []
    for item in _read_jsonl(cycles_path()):
        if item.get("type") != "cycle":
            continue
        try:
            cycle = AutonomyCycle(
                cycle_id=str(item.get("cycle_id") or ""),
                cwd=str(item.get("cwd") or ""),
                created_at=int(item.get("created_at") or 0),
                reflected=int(item.get("reflected") or 0),
                goal_reviews=int(item.get("goal_reviews") or 0),
                mission_steps=int(item.get("mission_steps") or 0),
                scheduled_jobs=int(item.get("scheduled_jobs") or 0),
                    monitor_changes=int(item.get("monitor_changes") or 0),
                    memory_promotions=int(item.get("memory_promotions") or 0),
                    upgrade_ideas=int(item.get("upgrade_ideas") or 0),
                    forged_skills=[str(value) for value in item.get("forged_skills", [])],
                lessons_added=int(item.get("lessons_added") or 0),
                notes=[str(value) for value in item.get("notes", [])],
            )
        except Exception:
            continue
        if not cycle.cycle_id:
            continue
        if not root or cycle.cwd == root:
            out.append(cycle)
    out.sort(key=lambda item: item.created_at, reverse=True)
    return out[: max(1, limit)]


def prompt_section(cwd: str | Path, *, limit: int = 3) -> str:
    cycles = list_cycles(cwd, limit=limit)
    if not cycles:
        return ""
    lines = ["# Autonomy Status"]
    for cycle in cycles:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(cycle.created_at))
        lines.append(
            f"- {when}: {cycle.reflected} reflection(s), "
            f"{cycle.goal_reviews} goal review(s), {cycle.mission_steps} mission step(s), "
            f"{cycle.scheduled_jobs} scheduled job(s), "
            f"{cycle.monitor_changes} monitor change(s), "
            f"{cycle.memory_promotions} memory promotion(s), "
            f"{cycle.upgrade_ideas} upgrade idea(s), {cycle.lessons_added} lesson(s)"
        )
        for note in cycle.notes[:2]:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def format_cycles(cwd: str | Path, *, limit: int = 12) -> str:
    cycles = list_cycles(cwd, limit=limit)
    if not cycles:
        return "no autonomy cycles found"
    lines = []
    for cycle in cycles:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(cycle.created_at))
        lines.append(
            f"{cycle.cycle_id} {when} - reflected={cycle.reflected} "
            f"goals={cycle.goal_reviews} missions={cycle.mission_steps} "
            f"schedules={cycle.scheduled_jobs} "
            f"monitors={cycle.monitor_changes} "
            f"memories={cycle.memory_promotions} upgrades={cycle.upgrade_ideas} lessons={cycle.lessons_added}"
        )
        for note in cycle.notes[:3]:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def _review_goals(root: Path, notes: list[str]) -> int:
    reviewed = 0
    for goal in goals.due_goals(root):
        lesson = learning.add_lesson(
            f"Autonomy goal review: keep working toward '{goal.title}'. "
            f"Success metric: {goal.success_metric or 'not specified'}.",
            cwd=root,
            scope="project",
            tags=["autonomy", "goal"],
            source="autonomy",
            confidence=0.62,
        )
        goals.update_goal(
            goal.goal_id,
            last_result=f"Autonomy reviewed goal and added lesson {lesson.lesson_id}.",
        )
        reviewed += 1
        notes.append(f"reviewed goal {goal.goal_id}: {goal.title}")
    return reviewed


def _forge_from_repeated_lessons(root: Path, notes: list[str], *, force: bool) -> list[str]:
    forged: list[str] = []
    tags: dict[str, int] = {}
    for lesson in learning.list_lessons(root):
        for tag in lesson.tags:
            tags[tag] = tags.get(tag, 0) + 1
    candidates = [
        tag for tag, count in sorted(tags.items(), key=lambda item: item[1], reverse=True)
        if count >= (2 if force else 4) and tag not in {"project", "autonomy"}
    ]
    for tag in candidates[:2]:
        try:
            result = skill_forge.forge_skill(root, topic=tag, min_lessons=2 if force else 3)
        except Exception:
            continue
        forged.append(result.skill_name)
        notes.append(f"forged skill ${result.skill_name} from repeated {tag} lessons")
    return forged


def _append(cycle: AutonomyCycle) -> None:
    path = cycles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"schema": SCHEMA_VERSION, "type": "cycle", **asdict(cycle)},
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
