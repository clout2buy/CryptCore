"""Persistent artifact studio for generated files.

The lifecycle tracker is intentionally lightweight and in-memory. This module
keeps the durable, UI-facing artifact index grouped by autonomous work thread.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import redact, session, settings, work_threads


SCHEMA_VERSION = 1
PREVIEW_BYTES = 16_000
PREVIEW_CHARS = 1_800
RECENT_THREAD_SECONDS = 30 * 60
ARTIFACT_STATUSES = {"created", "ready", "opened", "verified", "failed", "stale"}


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    path: str
    rel_path: str
    name: str
    kind: str
    status: str = "ready"
    mission_id: str = ""
    thread_id: str = ""
    mission_title: str = ""
    provenance: str = ""
    source: str = "runtime"
    preview: str = ""
    size: int = 0
    created_at: int = 0
    updated_at: int = 0
    verified_at: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ArtifactGroup:
    group_id: str
    title: str
    status: str
    count: int
    artifacts: list[ArtifactRecord] = field(default_factory=list)


def studio_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "artifacts.json"


def record_artifact(
    cwd: str | Path,
    path: str | Path,
    *,
    mission_id: str = "",
    thread_id: str = "",
    kind: str = "",
    status: str = "ready",
    provenance: str = "",
    source: str = "runtime",
    preview: str = "",
    note: str = "",
    attach_recent: bool = True,
) -> ArtifactRecord:
    """Create or update the durable artifact entry for ``path``."""
    root = Path(cwd).expanduser().resolve()
    artifact_path = _resolve_path(root, path)
    now = _now()
    existing = _existing_for_path(root, artifact_path)
    thread = _resolve_thread(root, mission_id=mission_id, thread_id=thread_id)
    if thread is None and attach_recent:
        thread = _recent_thread(root, now=now)
    if thread is not None:
        mission_id = thread.goal_id
        thread_id = thread.thread_id
        mission_title = thread.title
    else:
        mission_title = ""
    rel_path = _rel(root, artifact_path)
    clean_status = _status(status, artifact_path)
    if not preview:
        preview = preview_for_path(artifact_path)
    created_at = existing.created_at if existing else now
    notes = [*(existing.notes if existing else [])]
    if note:
        notes = _dedupe([note, *notes])[:10]
    record = ArtifactRecord(
        artifact_id=existing.artifact_id if existing else _artifact_id(root, artifact_path),
        path=str(artifact_path),
        rel_path=rel_path,
        name=artifact_path.name or rel_path,
        kind=kind or _infer_kind(artifact_path),
        status=clean_status,
        mission_id=mission_id,
        thread_id=thread_id,
        mission_title=mission_title,
        provenance=redact.text(provenance or (existing.provenance if existing else "")),
        source=source or (existing.source if existing else "runtime"),
        preview=redact.text(preview),
        size=_size(artifact_path),
        created_at=created_at,
        updated_at=now,
        verified_at=now if clean_status == "verified" else (existing.verified_at if existing else 0),
        notes=notes,
    )
    records = [item for item in _read(root) if item.artifact_id != record.artifact_id and item.path != record.path]
    records.insert(0, record)
    _write(root, records)
    _attach_to_thread(thread, rel_path, source=source)
    return record


def update_status(
    cwd: str | Path,
    path: str | Path,
    *,
    status: str,
    provenance: str = "",
    source: str = "runtime",
    note: str = "",
) -> ArtifactRecord | None:
    root = Path(cwd).expanduser().resolve()
    artifact_path = _resolve_path(root, path)
    existing = _existing_for_path(root, artifact_path)
    if existing is None:
        return None
    return record_artifact(
        root,
        artifact_path,
        mission_id=existing.mission_id,
        thread_id=existing.thread_id,
        kind=existing.kind,
        status=status,
        provenance=provenance or existing.provenance,
        source=source,
        preview=existing.preview,
        note=note,
        attach_recent=False,
    )


def list_artifacts(
    cwd: str | Path,
    *,
    mission_id: str = "",
    include_stale: bool = True,
    limit: int = 100,
) -> list[ArtifactRecord]:
    records = [_current_status(record) for record in _read(cwd)]
    if mission_id:
        records = [
            record
            for record in records
            if record.mission_id == mission_id or record.thread_id == mission_id
        ]
    if not include_stale:
        records = [record for record in records if record.status != "stale"]
    records.sort(key=lambda record: record.updated_at, reverse=True)
    return records[: max(1, limit)]


def group_artifacts(cwd: str | Path, *, limit: int = 100) -> list[ArtifactGroup]:
    root = Path(cwd).expanduser().resolve()
    records = list_artifacts(root, limit=limit)
    threads = {thread.thread_id: thread for thread in work_threads.list_threads(root, include_all=True)}
    by_goal = {thread.goal_id: thread for thread in threads.values()}
    grouped: dict[str, list[ArtifactRecord]] = {}
    for record in records:
        group_id = record.thread_id or record.mission_id or "workspace"
        grouped.setdefault(group_id, []).append(record)
    groups: list[ArtifactGroup] = []
    for group_id, items in grouped.items():
        thread = threads.get(group_id) or by_goal.get(group_id)
        title = (
            thread.title
            if thread is not None
            else (items[0].mission_title or "Workspace artifacts")
        )
        status = thread.state if thread is not None else "workspace"
        groups.append(ArtifactGroup(group_id=group_id, title=title, status=status, count=len(items), artifacts=items[:8]))
    groups.sort(key=lambda group: max((item.updated_at for item in group.artifacts), default=0), reverse=True)
    return groups


def snapshot(cwd: str | Path, *, limit: int = 60) -> dict[str, Any]:
    records = list_artifacts(cwd, limit=limit)
    groups = group_artifacts(cwd, limit=limit)
    return {
        "artifacts": [asdict(record) for record in records],
        "groups": [
            {
                **asdict(group),
                "artifacts": [asdict(record) for record in group.artifacts],
            }
            for group in groups
        ],
        "summary": {
            "total": len(records),
            "verified": sum(1 for record in records if record.status == "verified"),
            "missionLinked": sum(1 for record in records if record.thread_id or record.mission_id),
            "stale": sum(1 for record in records if record.status == "stale"),
        },
    }


def preview_for_path(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        return "File no longer exists."
    if p.is_dir():
        return "Folder artifact."
    kind = _infer_kind(p)
    if kind in {"image", "screenshot", "video", "pdf", "spreadsheet", "deck"}:
        return f"{kind.title()} artifact ({_size_label(_size(p))})."
    try:
        with p.open("rb") as f:
            raw = f.read(PREVIEW_BYTES)
    except OSError:
        return "Preview unavailable."
    if b"\x00" in raw:
        return f"{kind.title()} artifact ({_size_label(_size(p))})."
    text = raw.decode("utf-8", errors="replace")
    lines = [line.rstrip() for line in text.splitlines()[:18]]
    preview = "\n".join(lines).strip()
    if len(preview) > PREVIEW_CHARS:
        preview = preview[:PREVIEW_CHARS].rstrip() + "\n..."
    if not preview:
        preview = "Empty text artifact."
    return redact.text(preview)


def _read(cwd: str | Path) -> list[ArtifactRecord]:
    path = studio_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[ArtifactRecord] = []
    for item in data.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        record = _record_from_dict(item)
        if record is not None:
            out.append(record)
    return out


def _write(cwd: str | Path, records: list[ArtifactRecord]) -> None:
    path = studio_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema": SCHEMA_VERSION, "artifacts": [asdict(record) for record in records[:250]]}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.restrict_file_permissions(path)


def _record_from_dict(data: dict[str, Any]) -> ArtifactRecord | None:
    try:
        return ArtifactRecord(
            artifact_id=str(data.get("artifact_id") or ""),
            path=str(data.get("path") or ""),
            rel_path=str(data.get("rel_path") or data.get("path") or ""),
            name=str(data.get("name") or Path(str(data.get("path") or "")).name),
            kind=str(data.get("kind") or "file"),
            status=str(data.get("status") or "ready"),
            mission_id=str(data.get("mission_id") or ""),
            thread_id=str(data.get("thread_id") or ""),
            mission_title=str(data.get("mission_title") or ""),
            provenance=str(data.get("provenance") or ""),
            source=str(data.get("source") or "runtime"),
            preview=str(data.get("preview") or ""),
            size=int(data.get("size") or 0),
            created_at=int(data.get("created_at") or 0),
            updated_at=int(data.get("updated_at") or 0),
            verified_at=int(data.get("verified_at") or 0),
            notes=[str(item) for item in data.get("notes", []) if str(item).strip()],
        )
    except Exception:
        return None


def _resolve_path(root: Path, path: str | Path) -> Path:
    p = Path(path).expanduser()
    return (p if p.is_absolute() else root / p).resolve()


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _artifact_id(root: Path, path: Path) -> str:
    raw = f"{root}\0{path}".encode("utf-8", errors="replace")
    return "art_" + hashlib.sha1(raw).hexdigest()[:16]


def _existing_for_path(root: Path, path: Path) -> ArtifactRecord | None:
    path_text = str(path)
    return next((record for record in _read(root) if record.path == path_text), None)


def _resolve_thread(root: Path, *, mission_id: str = "", thread_id: str = "") -> work_threads.WorkThread | None:
    mission_id = str(mission_id or "").strip()
    thread_id = str(thread_id or "").strip()
    if not mission_id and not thread_id:
        return None
    for thread in work_threads.list_threads(root, include_all=True):
        if thread.thread_id == thread_id or thread.goal_id == mission_id or thread.thread_id == mission_id:
            return thread
    return None


def _recent_thread(root: Path, *, now: int) -> work_threads.WorkThread | None:
    candidates = [
        thread
        for thread in work_threads.list_threads(root)
        if thread.updated_at and now - thread.updated_at <= RECENT_THREAD_SECONDS
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda thread: thread.updated_at, reverse=True)
    return candidates[0]


def _attach_to_thread(thread: work_threads.WorkThread | None, rel_path: str, *, source: str) -> None:
    if thread is None or rel_path in thread.artifacts:
        return
    try:
        work_threads.update_thread(
            thread.thread_id,
            artifacts=[rel_path],
            last_note=f"artifact recorded: {rel_path}",
            source=source or "artifact-studio",
        )
    except Exception:
        return


def _status(status: str, path: Path) -> str:
    clean = str(status or "ready").strip().lower()
    if clean not in ARTIFACT_STATUSES:
        clean = "ready"
    if clean not in {"failed", "stale"} and not path.exists():
        return "stale"
    return clean


def _current_status(record: ArtifactRecord) -> ArtifactRecord:
    if record.status in {"failed", "stale"}:
        return record
    try:
        exists = Path(record.path).exists()
    except OSError:
        exists = False
    return record if exists else replace(record, status="stale")


def _infer_kind(path: Path) -> str:
    if path.is_dir():
        return "folder"
    name = path.name.lower()
    suffix = path.suffix.lower()
    if "screenshot" in name or "screen-shot" in name:
        return "screenshot"
    if suffix in {".html", ".htm"}:
        return "site"
    if suffix in {".md", ".markdown", ".txt", ".rst"}:
        return "document"
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".ps1", ".bat", ".sh"}:
        return "script"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        return "image"
    if suffix in {".mp4", ".webm", ".mov", ".mkv"}:
        return "video"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".docx":
        return "document"
    if suffix == ".xlsx":
        return "spreadsheet"
    if suffix == ".pptx":
        return "deck"
    if suffix in {".json", ".yaml", ".yml", ".csv"}:
        return "data"
    return "file"


def _size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _size_label(size: int) -> str:
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.1f} KB"
    return f"{size} B"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = str(item).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _now() -> int:
    return int(time.time())
