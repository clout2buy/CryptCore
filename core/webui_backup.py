"""Backup and restore for non-secret WebUI state."""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from . import agent_profiles, goals, memory_journal, settings, skills, soul, work_threads


SCHEMA_VERSION = 1
MAX_RESTORE_BYTES = 5_000_000


def export_backup(cwd: str | Path) -> dict[str, Any]:
    workspace = Path(cwd).expanduser().resolve()
    files = []
    for path in _backup_paths(workspace):
        if path.exists() and path.is_file():
            files.append(_pack_file(path))
    return {
        "schema": SCHEMA_VERSION,
        "exported_at": int(time.time()),
        "workspace": str(workspace),
        "note": "Non-secret Crypt WebUI state. Auth tokens and provider credentials are intentionally excluded.",
        "files": files,
        "summary": {
            "goals": len(goals.list_goals(workspace, include_all=True)),
            "threads": len(work_threads.list_threads(workspace, include_all=True)),
            "agents": len(agent_profiles.list_profiles(workspace)),
            "skills": len(skills.discover(workspace, include_disabled=True)),
        },
    }


def restore_backup(cwd: str | Path, backup: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(backup, dict) or int(backup.get("schema") or 0) != SCHEMA_VERSION:
        raise ValueError("unsupported backup schema")
    workspace = Path(cwd).expanduser().resolve()
    restored = []
    total = 0
    for item in backup.get("files", []):
        if not isinstance(item, dict):
            continue
        target = _target_path(workspace, str(item.get("scope") or ""), str(item.get("rel_path") or ""))
        if target is None:
            continue
        data = base64.b64decode(str(item.get("content_b64") or ""), validate=True)
        total += len(data)
        if total > MAX_RESTORE_BYTES:
            raise ValueError("backup restore exceeds safe size limit")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        settings.restrict_file_permissions(target)
        restored.append(str(target))
    return {"restored": restored, "count": len(restored)}


def _backup_paths(workspace: Path) -> list[Path]:
    return [
        goals.goals_path(),
        work_threads.threads_path(),
        memory_journal.memory_path(),
        soul.ensure_soul(),
        agent_profiles.store_path(workspace),
        *(skill.path for skill in skills.discover(workspace, include_disabled=True) if _safe_skill_path(workspace, skill.path)),
    ]


def _pack_file(path: Path) -> dict[str, str]:
    scope, rel_path = _scope_for_path(path)
    return {
        "scope": scope,
        "rel_path": rel_path,
        "content_b64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def _scope_for_path(path: Path) -> tuple[str, str]:
    resolved = path.expanduser().resolve()
    app_root = settings.APP_DIR.expanduser().resolve()
    if resolved == app_root or app_root in resolved.parents:
        return "app", resolved.relative_to(app_root).as_posix()
    return "workspace", resolved.as_posix()


def _target_path(workspace: Path, scope: str, rel_path: str) -> Path | None:
    if not rel_path or ".." in Path(rel_path).parts:
        return None
    if scope == "app":
        return (settings.APP_DIR / rel_path).expanduser().resolve()
    if scope == "workspace":
        target = Path(rel_path)
        if target.is_absolute():
            try:
                target.relative_to(workspace)
            except ValueError:
                return None
            return target
        return (workspace / rel_path).resolve()
    return None


def _safe_skill_path(workspace: Path, path: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(workspace)
    except ValueError:
        return False
    return path.name == "SKILL.md"
