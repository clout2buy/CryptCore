"""Safe self-upgrade sandbox planning and merge readiness records."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import session, settings, upgrade_queue


SCHEMA_VERSION = 1
STATUSES = {"planned", "running", "verified", "proposed", "merged", "failed", "cancelled"}


@dataclass(frozen=True)
class SandboxRecord:
    sandbox_id: str
    cwd: str
    title: str
    idea_id: str = ""
    branch: str = ""
    worktree_path: str = ""
    status: str = "planned"
    checks: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    merge_notes: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0


def sandbox_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "upgrades" / "sandboxes.json"


def plan(
    cwd: str | Path,
    *,
    title: str,
    idea_id: str = "",
    checks: list[str] | None = None,
) -> SandboxRecord:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    sandbox_id = "sbox_" + hashlib.sha1(f"{root}\0{title}\0{idea_id}".encode("utf-8", errors="replace")).hexdigest()[:12]
    existing = {item.sandbox_id: item for item in list_sandboxes(root, include_all=True)}
    branch = "codex/upgrade-" + _slug(title)[:48]
    record = SandboxRecord(
        sandbox_id=sandbox_id,
        cwd=str(root),
        title=_clean(title, 160),
        idea_id=_clean(idea_id, 120),
        branch=branch,
        worktree_path=str(session.project_dir(root) / "upgrade-sandboxes" / sandbox_id),
        status=existing.get(sandbox_id).status if sandbox_id in existing else "planned",
        checks=checks or _default_checks(),
        changed_paths=existing.get(sandbox_id).changed_paths if sandbox_id in existing else [],
        merge_notes=existing.get(sandbox_id).merge_notes if sandbox_id in existing else [],
        created_at=existing.get(sandbox_id).created_at if sandbox_id in existing else now,
        updated_at=now,
    )
    existing[sandbox_id] = record
    _write(root, list(existing.values()))
    return record


def plan_from_idea(cwd: str | Path, idea_id: str) -> SandboxRecord:
    idea = next((item for item in upgrade_queue.list_ideas(cwd, include_all=True) if item.idea_id == idea_id), None)
    if idea is None:
        raise KeyError(f"upgrade idea not found: {idea_id}")
    return plan(cwd, title=idea.title, idea_id=idea.idea_id)


def record_result(
    cwd: str | Path,
    sandbox_id: str,
    *,
    status: str,
    checks: list[str] | None = None,
    changed_paths: list[str] | None = None,
    note: str = "",
) -> SandboxRecord:
    clean_status = str(status or "").strip().lower()
    if clean_status not in STATUSES:
        raise ValueError(f"unknown sandbox status: {status}")
    return _replace(
        cwd,
        sandbox_id,
        status=clean_status,
        checks=checks,
        changed_paths=changed_paths,
        note=note,
    )


def propose_merge(cwd: str | Path, sandbox_id: str, *, note: str = "") -> SandboxRecord:
    return _replace(cwd, sandbox_id, status="proposed", note=note or "ready to propose merge after verification")


def list_sandboxes(cwd: str | Path, *, include_all: bool = False, limit: int = 40) -> list[SandboxRecord]:
    root = str(Path(cwd).expanduser().resolve())
    records = [item for item in _read(cwd) if item.cwd == root]
    if not include_all:
        records = [item for item in records if item.status not in {"merged", "cancelled"}]
    records.sort(key=lambda item: item.updated_at, reverse=True)
    return records[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    records = list_sandboxes(cwd, include_all=True, limit=80)
    counts: dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    return {
        "path": str(sandbox_path(cwd)),
        "total": len(records),
        "statusCounts": counts,
        "records": [asdict(record) for record in records[:20]],
    }


def prompt_section(cwd: str | Path) -> str:
    records = list_sandboxes(cwd, limit=5)
    if not records:
        return ""
    lines = ["# Self-Upgrade Sandbox"]
    for record in records:
        lines.append(
            f"- {record.status} {record.title}: branch={record.branch}; "
            f"checks={'; '.join(record.checks[:3])}"
        )
    return "\n".join(lines)


def _replace(cwd: str | Path, sandbox_id: str, **values: Any) -> SandboxRecord:
    records = list_sandboxes(cwd, include_all=True, limit=200)
    out: list[SandboxRecord] = []
    updated: SandboxRecord | None = None
    now = _now()
    for record in records:
        if record.sandbox_id != sandbox_id:
            out.append(record)
            continue
        data = asdict(record)
        if "status" in values and values["status"] is not None:
            data["status"] = values["status"]
        if values.get("checks") is not None:
            data["checks"] = [_clean(item, 220) for item in values["checks"] if str(item).strip()]
        if values.get("changed_paths") is not None:
            data["changed_paths"] = [_clean(item, 240) for item in values["changed_paths"] if str(item).strip()]
        if values.get("note"):
            data["merge_notes"] = [_clean(values["note"], 500), *record.merge_notes[:20]]
        data["updated_at"] = now
        updated = SandboxRecord(**data)
        out.append(updated)
    if updated is None:
        raise KeyError(f"sandbox not found: {sandbox_id}")
    _write(cwd, out)
    return updated


def _read(cwd: str | Path) -> list[SandboxRecord]:
    path = sandbox_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[SandboxRecord] = []
    for item in data.get("sandboxes", []):
        if not isinstance(item, dict):
            continue
        try:
            status = str(item.get("status") or "planned").lower()
            if status not in STATUSES:
                status = "planned"
            out.append(
                SandboxRecord(
                    sandbox_id=str(item.get("sandbox_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    title=str(item.get("title") or ""),
                    idea_id=str(item.get("idea_id") or ""),
                    branch=str(item.get("branch") or ""),
                    worktree_path=str(item.get("worktree_path") or ""),
                    status=status,
                    checks=[str(value) for value in item.get("checks", []) if str(value).strip()],
                    changed_paths=[str(value) for value in item.get("changed_paths", []) if str(value).strip()],
                    merge_notes=[str(value) for value in item.get("merge_notes", []) if str(value).strip()],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [item for item in out if item.sandbox_id and item.title]


def _write(cwd: str | Path, records: list[SandboxRecord]) -> None:
    path = sandbox_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "sandboxes": [asdict(item) for item in records[:200]]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _default_checks() -> list[str]:
    return ["python -m py_compile core\\*.py", "node --check core\\webui_static\\app.js", "scripts\\verify_core.ps1 -Quick"]


def _slug(value: str) -> str:
    clean = "-".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))
    return clean or "self-upgrade"


def _clean(value: object, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
