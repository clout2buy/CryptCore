"""Quality rubric for generated and installed SKILL.md bundles."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import settings, skills


SCHEMA_VERSION = 1
READY_THRESHOLD = 0.72
BLOCK_THRESHOLD = 0.45
STATE_FILE = ".crypt-skill-state.json"


@dataclass(frozen=True)
class RubricCheck:
    name: str
    score: float
    max_score: float
    status: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillQualityScore:
    name: str
    path: str
    score: float
    status: str
    checks: list[RubricCheck] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checks"] = [check.to_dict() for check in self.checks]
        return data


def score_path(path: str | Path, *, name: str = "") -> SkillQualityScore:
    skill_path = Path(path).expanduser().resolve()
    try:
        text = skill_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return score_text(text, path=skill_path, name=name or skill_path.parent.name)


def score_skill(skill: skills.Skill) -> SkillQualityScore:
    return score_path(skill.path, name=skill.name)


def score_text(text: str, *, path: str | Path = "", name: str = "") -> SkillQualityScore:
    text = str(text or "")
    frontmatter, body = _split_frontmatter(text)
    lowered = text.lower()
    checks = [
        _check("metadata", 15, bool(frontmatter.get("name")) and bool(frontmatter.get("description")), "name and description front matter"),
        _check("trigger clarity", 15, _has_any(lowered, ("use this skill when", "use when", "trigger", "examples:")), "clear activation language or examples"),
        _check("workflow", 20, _has_any(lowered, ("workflow", "operating rules", "steps", "procedure", "instructions")), "actionable workflow instructions"),
        _check("verification", 15, _has_any(lowered, ("smoke_tests", "smoke tests", "verification", "tests", "verify")), "verification or smoke test guidance"),
        _check("safety boundaries", 15, _has_any(lowered, ("conflict", "safety", "approval", "do not", "boundary", "user instructions")), "safety and priority boundaries"),
        _check("tool boundaries", 10, _has_any(lowered, ("tool", "browser", "files", "commands", "workspace", "api", "mcp")), "tool or workspace boundaries"),
        _check("examples", 10, bool(frontmatter.get("examples")) or _has_any(body.lower(), ("## examples", "# examples", "example")), "usage examples"),
    ]
    blockers = []
    if not text.strip():
        blockers.append("skill file is empty or unreadable")
    if skills._blocked_reason(text):  # Keep the existing injection detector as a hard gate.
        blockers.append(skills._blocked_reason(text))
    if not frontmatter.get("name"):
        blockers.append("missing frontmatter name")
    if not frontmatter.get("description"):
        blockers.append("missing frontmatter description")
    raw_score = sum(check.score for check in checks) / sum(check.max_score for check in checks)
    status = "ready"
    if blockers or raw_score < BLOCK_THRESHOLD:
        status = "blocked"
    elif raw_score < READY_THRESHOLD:
        status = "needs-work"
    recommendations = _recommendations(checks, blockers)
    return SkillQualityScore(
        name=skills._safe_name(name or frontmatter.get("name") or "skill"),
        path=str(Path(path).expanduser().resolve()) if path else "",
        score=round(raw_score, 2),
        status=status,
        checks=checks,
        blockers=blockers,
        recommendations=recommendations,
        updated_at=int(time.time()),
    )


def audit(cwd: str | Path, *, include_disabled: bool = True) -> list[SkillQualityScore]:
    return [score_skill(skill) for skill in skills.discover(cwd, include_disabled=include_disabled)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    scores = audit(cwd, include_disabled=True)
    ready = [score for score in scores if score.status == "ready"]
    needs_work = [score for score in scores if score.status == "needs-work"]
    blocked = [score for score in scores if score.status == "blocked"]
    average = round(sum(score.score for score in scores) / len(scores), 2) if scores else 0.0
    return {
        "schema": SCHEMA_VERSION,
        "total": len(scores),
        "ready": len(ready),
        "needsWork": len(needs_work),
        "blocked": len(blocked),
        "averageScore": average,
        "scores": [score.to_dict() for score in sorted(scores, key=lambda item: (item.status != "ready", item.score), reverse=True)[:30]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    scores = audit(cwd, include_disabled=True)
    weak = [score for score in scores if score.status != "ready"]
    if not weak:
        return ""
    lines = ["# Skill Quality Rubric"]
    for score in weak[:limit]:
        issue = "; ".join(score.blockers or score.recommendations[:2])
        lines.append(f"- ${score.name}: {score.status} score={score.score:.2f}; {issue}")
    return "\n".join(lines)


def apply_promotion_gate(skill_path: str | Path, score: SkillQualityScore | None = None) -> SkillQualityScore:
    path = Path(skill_path).expanduser().resolve()
    score = score or score_path(path)
    state_path = path.parent / STATE_FILE
    state = _read_state(state_path)
    state.update(
        {
            "quality_score": score.score,
            "quality_status": score.status,
            "quality_recommendations": score.recommendations[:6],
            "quality_updated_at": score.updated_at,
            "managed_by": "crypt-skill-quality-rubric",
        }
    )
    if score.status == "blocked":
        state["enabled"] = False
        state["reason"] = "; ".join(score.blockers or score.recommendations or ["quality score below promotion threshold"])
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    settings.restrict_file_permissions(state_path)
    return score


def _check(name: str, max_score: float, passed: bool, detail: str) -> RubricCheck:
    return RubricCheck(
        name=name,
        score=max_score if passed else 0.0,
        max_score=max_score,
        status="pass" if passed else "missing",
        detail=detail,
    )


def _recommendations(checks: list[RubricCheck], blockers: list[str]) -> list[str]:
    out = list(blockers)
    for check in checks:
        if check.status != "pass":
            out.append(f"Add {check.detail}.")
    return out[:8]


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for idx, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = idx
            break
    if end is None:
        return {}, text
    data: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip().lower().replace("-", "_")] = value.strip().strip('"').strip("'")
    return data, "\n".join(lines[end + 1 :])


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
