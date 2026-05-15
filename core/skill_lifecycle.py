"""Lifecycle state for local SKILL.md bundles."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import settings, skills


STATE_FILE = ".crypt-skill-state.json"


@dataclass(frozen=True)
class SkillLifecycleCard:
    name: str
    path: str
    enabled: bool
    status: str
    trust_level: str
    version: str
    source: str = ""
    blocked_reason: str = ""
    provenance: str = ""
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def set_enabled(cwd: str | Path, name: str, enabled: bool, *, reason: str = "") -> SkillLifecycleCard:
    skill = _find(cwd, name)
    if skill is None:
        raise KeyError(f"unknown skill: {name}")
    state = _state(skill.path.parent)
    state.update(
        {
            "enabled": bool(enabled),
            "reason": _clean(reason, 500),
            "updated_at": _now(),
            "managed_by": "crypt-skill-lifecycle",
        }
    )
    _write_state(skill.path.parent, state)
    refreshed = _find(cwd, name, include_disabled=True) or skill
    return _card(refreshed)


def audit(cwd: str | Path, *, include_disabled: bool = True) -> list[SkillLifecycleCard]:
    return [_card(skill) for skill in skills.discover(cwd, include_disabled=include_disabled)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    cards = audit(cwd, include_disabled=True)
    return {
        "total": len(cards),
        "enabled": sum(1 for card in cards if card.enabled),
        "disabled": sum(1 for card in cards if not card.enabled and card.status == "disabled"),
        "blocked": sum(1 for card in cards if card.status == "blocked"),
        "skills": [card.to_dict() for card in cards],
    }


def prompt_section(cwd: str | Path, *, limit: int = 12) -> str:
    cards = audit(cwd, include_disabled=True)[: max(1, limit)]
    if not cards:
        return ""
    lines = ["# Skill Lifecycle"]
    for card in cards:
        lines.append(f"- ${card.name}: {card.status}; version={card.version}; source={card.source}; {card.blocked_reason}")
    return "\n".join(lines)


def runtime_state(skill_dir: Path) -> dict[str, Any]:
    return _state(skill_dir)


def _card(skill: skills.Skill) -> SkillLifecycleCard:
    state = _state(skill.path.parent)
    status = "enabled" if skill.enabled else ("blocked" if skill.blocked_reason and state.get("enabled") is not False else "disabled")
    source = str((skill.metadata or {}).get("source") or skill.trust_level)
    return SkillLifecycleCard(
        name=skill.name,
        path=str(skill.path),
        enabled=skill.enabled,
        status=status,
        trust_level=skill.trust_level,
        version=_folder_hash(skill.path.parent)[:12],
        source=source,
        blocked_reason=skill.blocked_reason,
        provenance=str((skill.metadata or {}).get("root") or skill.path.parent),
        updated_at=int(state.get("updated_at") or _mtime(skill.path)),
    )


def _find(cwd: str | Path, name: str, *, include_disabled: bool = True) -> skills.Skill | None:
    clean = skills._safe_name(name)  # Reuse canonical skill names.
    return next((skill for skill in skills.discover(cwd, include_disabled=include_disabled) if skill.name == clean), None)


def _state(skill_dir: Path) -> dict[str, Any]:
    path = skill_dir / STATE_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(skill_dir: Path, state: dict[str, Any]) -> None:
    path = skill_dir / STATE_FILE
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    settings.restrict_file_permissions(path)


def _folder_hash(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.name == STATE_FILE or not path.is_file():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        h.update(rel.encode("utf-8", errors="replace"))
        h.update(b"\0")
        try:
            h.update(path.read_bytes())
        except OSError:
            continue
        h.update(b"\0")
    return h.hexdigest()


def _mtime(path: Path) -> int:
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
