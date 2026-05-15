"""Import local data files into Crypt memory, artifacts, entities, and missions."""
from __future__ import annotations

import csv
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import artifact_studio, entities, goals, memory_journal, redact, session, settings


SCHEMA_VERSION = 1
TEXT_SUFFIXES = {".md", ".txt", ".log"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
DATA_SUFFIXES = {".json", ".jsonl", ".csv", ".tsv"}
DESTINATIONS = {"auto", "memory", "entities", "mission", "artifact-only"}


@dataclass(frozen=True)
class ImportRecord:
    import_id: str
    source_path: str
    rel_path: str
    kind: str
    destination: str = "auto"
    status: str = "imported"
    title: str = ""
    preview: str = ""
    artifact_id: str = ""
    memory_changed: bool = False
    entity_count: int = 0
    mission_id: str = ""
    rows: int = 0
    columns: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    size: int = 0
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def registry_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "data-imports" / "imports.json"


def import_file(
    cwd: str | Path,
    path: str | Path,
    *,
    destination: str = "auto",
    title: str = "",
) -> ImportRecord:
    root = Path(cwd).expanduser().resolve()
    source = _resolve(root, path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))
    clean_destination = _destination(destination)
    inspected = inspect_file(root, source)
    preview = inspected["preview"]
    artifact = artifact_studio.record_artifact(
        root,
        source,
        kind=f"import:{inspected['kind']}",
        status="ready",
        provenance=f"Imported into Crypt data layer as {clean_destination}",
        source="data-importer",
        preview=preview,
        note="data import registered",
    )
    memory_changed = False
    entity_count = 0
    mission_id = ""
    if clean_destination in {"auto", "memory"} and inspected["kind"] != "image":
        memory = memory_journal.observe(
            root,
            f"Imported {inspected['kind']} file {inspected['rel_path']}: {preview}",
            source="data-importer",
        )
        memory_changed = memory.changed
    if clean_destination in {"auto", "entities"} and inspected["kind"] in {"markdown", "note", "json", "csv", "browser-export"}:
        observed = entities.observe_text(root, preview, source="data-importer")
        entity_count = observed.count
    if clean_destination == "mission" or (clean_destination == "auto" and _looks_like_mission(source, preview)):
        mission = goals.add_goal(
            title or f"Import follow-up: {source.stem}",
            description=f"Review imported {inspected['kind']} data from {inspected['rel_path']}.",
            workspace=root,
            success_metric="Imported data reviewed and converted into next actions.",
            tags=["data-import", inspected["kind"]],
        )
        mission_id = mission.goal_id
    now = _now()
    record = ImportRecord(
        import_id="import_" + uuid.uuid4().hex[:10],
        source_path=str(source),
        rel_path=inspected["rel_path"],
        kind=inspected["kind"],
        destination=clean_destination,
        title=redact.text(title or source.stem)[:160],
        preview=preview,
        artifact_id=artifact.artifact_id,
        memory_changed=memory_changed,
        entity_count=entity_count,
        mission_id=mission_id,
        rows=int(inspected.get("rows") or 0),
        columns=list(inspected.get("columns") or []),
        keys=list(inspected.get("keys") or []),
        size=int(inspected.get("size") or 0),
        created_at=now,
        updated_at=now,
    )
    rows = list_imports(root, include_all=True)
    rows.insert(0, record)
    _write(root, rows)
    return record


def import_text(
    cwd: str | Path,
    title: str,
    text: str,
    *,
    destination: str = "memory",
) -> ImportRecord:
    root = Path(cwd).expanduser().resolve()
    clean_title = _safe_name(title or "imported-note")
    path = root / ".crypt" / "imports" / f"{clean_title}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact.text(str(text or "")).strip() + "\n", encoding="utf-8")
    settings.restrict_file_permissions(path)
    return import_file(root, path, destination=destination, title=title)


def inspect_file(cwd: str | Path, path: str | Path) -> dict[str, Any]:
    root = Path(cwd).expanduser().resolve()
    source = _resolve(root, path)
    suffix = source.suffix.lower()
    size = source.stat().st_size
    kind = _kind(source)
    rel_path = _rel(root, source)
    data: dict[str, Any] = {
        "kind": kind,
        "rel_path": rel_path,
        "size": size,
        "rows": 0,
        "columns": [],
        "keys": [],
        "preview": "",
    }
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        rows = _read_csv(source, delimiter=delimiter)
        headers = rows[0] if rows else []
        body = rows[1:4] if len(rows) > 1 else rows[:3]
        data.update({
            "rows": max(0, len(rows) - 1),
            "columns": headers[:20],
            "preview": _trim(f"columns={', '.join(headers[:12])}; sample={body[:2]}", 1_200),
        })
    elif suffix == ".json":
        parsed = _read_json(source)
        keys = _json_keys(parsed)
        data.update({"keys": keys[:30], "preview": _trim(json.dumps(parsed, ensure_ascii=False, indent=2), 1_500)})
    elif suffix == ".jsonl":
        lines = _read_text(source).splitlines()
        data.update({"rows": len(lines), "preview": _trim("\n".join(lines[:6]), 1_500)})
    elif suffix in TEXT_SUFFIXES:
        text = _read_text(source)
        data["preview"] = _trim(text, 1_500)
    elif suffix in IMAGE_SUFFIXES:
        data["preview"] = f"Image import: {source.name}, {size} bytes. Use visual QA or screenshot analysis before making claims."
    else:
        data["preview"] = artifact_studio.preview_for_path(source)
    if _looks_like_browser_export(source, data["preview"]):
        data["kind"] = "browser-export"
    if data["kind"] == "markdown" and "note" in source.stem.lower():
        data["kind"] = "note"
    return data


def list_imports(cwd: str | Path, *, include_all: bool = False, limit: int = 80) -> list[ImportRecord]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status == "imported"]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_imports(cwd, include_all=True, limit=50)
    return {
        "total": len(rows),
        "byKind": _counts(row.kind for row in rows),
        "memoryLinked": sum(1 for row in rows if row.memory_changed),
        "missionsCreated": sum(1 for row in rows if row.mission_id),
        "imports": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_imports(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Data Imports"]
    for row in rows:
        linked = []
        if row.memory_changed:
            linked.append("memory")
        if row.entity_count:
            linked.append("entities")
        if row.mission_id:
            linked.append(f"mission={row.mission_id}")
        lines.append(f"- {row.kind}: {row.rel_path}; {'/'.join(linked) or 'artifact'}; {row.preview[:220]}")
    return "\n".join(lines)


def _read(cwd: str | Path) -> list[ImportRecord]:
    path = registry_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("imports", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                ImportRecord(
                    import_id=str(item.get("import_id") or ""),
                    source_path=str(item.get("source_path") or ""),
                    rel_path=str(item.get("rel_path") or ""),
                    kind=str(item.get("kind") or "unknown"),
                    destination=_destination(str(item.get("destination") or "auto")),
                    status=str(item.get("status") or "imported"),
                    title=str(item.get("title") or ""),
                    preview=str(item.get("preview") or ""),
                    artifact_id=str(item.get("artifact_id") or ""),
                    memory_changed=bool(item.get("memory_changed")),
                    entity_count=int(item.get("entity_count") or 0),
                    mission_id=str(item.get("mission_id") or ""),
                    rows=int(item.get("rows") or 0),
                    columns=[str(value) for value in item.get("columns", [])],
                    keys=[str(value) for value in item.get("keys", [])],
                    size=int(item.get("size") or 0),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.import_id and row.source_path]


def _write(cwd: str | Path, rows: list[ImportRecord]) -> None:
    path = registry_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "imports": [row.to_dict() for row in rows]}, indent=2),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _resolve(root: Path, path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return "markdown"
    if suffix in {".txt", ".log"}:
        return "note"
    if suffix in {".csv", ".tsv"}:
        return "csv"
    if suffix in {".json", ".jsonl"}:
        return "json"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    return "unknown"


def _destination(value: str) -> str:
    clean = str(value or "auto").strip().lower()
    return clean if clean in DESTINATIONS else "auto"


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {"error": "invalid json", "path": str(path)}


def _read_csv(path: Path, *, delimiter: str) -> list[list[str]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            return [[str(cell) for cell in row] for row in csv.reader(handle, delimiter=delimiter)][:60]
    except OSError:
        return []


def _json_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = [str(key) for key in value.keys()]
        for child in value.values():
            keys.extend(_json_keys(child)[:12])
        return _dedupe(keys)
    if isinstance(value, list):
        keys: list[str] = []
        for item in value[:10]:
            keys.extend(_json_keys(item)[:12])
        return _dedupe(keys)
    return []


def _looks_like_browser_export(path: Path, preview: str) -> bool:
    text = f"{path.name} {preview}".lower()
    return any(term in text for term in ("bookmark", "history", "browser", "url", "visited", "tabs"))


def _looks_like_mission(path: Path, preview: str) -> bool:
    text = f"{path.name} {preview}".lower()
    return any(term in text for term in ("mission", "todo", "next action", "goal", "due date", "blocker"))


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value).strip(".-")
    return safe[:80] or "imported-note"


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen: set[str] = set()
    for value in values:
        clean = str(value).strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _trim(value: str, limit: int) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
