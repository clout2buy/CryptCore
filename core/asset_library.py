"""Reusable asset library for local files and generated artifacts."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import artifact_studio, redact, session, settings


SCHEMA_VERSION = 1
ASSET_EXTENSIONS = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".gif": "image",
    ".svg": "image",
    ".mp4": "video",
    ".mov": "video",
    ".webm": "video",
    ".mp3": "audio",
    ".wav": "audio",
    ".pdf": "document",
    ".docx": "document",
    ".pptx": "deck",
    ".xlsx": "spreadsheet",
    ".csv": "data",
    ".html": "ui",
    ".css": "ui",
    ".js": "ui",
    ".tsx": "ui",
    ".jsx": "ui",
    ".md": "notes",
}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    path: str
    rel_path: str
    kind: str
    name: str
    purpose: str = ""
    provenance: str = ""
    source: str = "asset-library"
    reuse_hints: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    size: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def library_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "assets" / "library.json"


def record_asset(
    cwd: str | Path,
    path: str | Path,
    *,
    purpose: str = "",
    provenance: str = "",
    source: str = "manual",
    tags: list[str] | None = None,
) -> AssetRecord:
    root = Path(cwd).expanduser().resolve()
    asset_path = _resolve(root, path)
    record = _record(root, asset_path, purpose=purpose, provenance=provenance, source=source, tags=tags or [])
    records = [item for item in _read(root) if item.asset_id != record.asset_id and item.path != record.path]
    records.insert(0, record)
    _write(root, records)
    return record


def index_workspace(cwd: str | Path, *, limit: int = 120) -> list[AssetRecord]:
    root = Path(cwd).expanduser().resolve()
    found = []
    for path in _walk_assets(root, limit=limit):
        found.append(_record(root, path, source="workspace-index"))
    existing = {item.path: item for item in _read(root)}
    for record in found:
        existing[record.path] = record
    records = sorted(existing.values(), key=lambda item: item.updated_at, reverse=True)[:300]
    _write(root, records)
    return found


def list_assets(cwd: str | Path, *, limit: int = 120) -> list[AssetRecord]:
    root = Path(cwd).expanduser().resolve()
    persisted = _read(root)
    artifact_assets = [_from_artifact(root, item) for item in artifact_studio.list_artifacts(root, limit=80)]
    by_path: dict[str, AssetRecord] = {}
    for record in [*artifact_assets, *persisted]:
        by_path[record.path] = _current(record)
    records = list(by_path.values())
    records.sort(key=lambda item: item.updated_at, reverse=True)
    return records[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    records = list_assets(cwd, limit=120)
    by_kind: dict[str, int] = {}
    for record in records:
        by_kind[record.kind] = by_kind.get(record.kind, 0) + 1
    return {
        "schema": SCHEMA_VERSION,
        "total": len(records),
        "byKind": by_kind,
        "reusable": sum(1 for record in records if record.reuse_hints),
        "assets": [record.to_dict() for record in records[:40]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 8) -> str:
    records = list_assets(cwd, limit=limit)
    if not records:
        return ""
    lines = ["# Asset Library"]
    for record in records[:limit]:
        hint = "; ".join(record.reuse_hints[:2]) or record.purpose or record.provenance
        lines.append(f"- [{record.kind}] {record.rel_path}: {hint}")
    return "\n".join(lines)


def _record(
    root: Path,
    path: Path,
    *,
    purpose: str = "",
    provenance: str = "",
    source: str = "asset-library",
    tags: list[str] | None = None,
) -> AssetRecord:
    kind = _kind(path)
    rel_path = _rel(root, path)
    return AssetRecord(
        asset_id="asset_" + artifact_studio._artifact_id(root, path).replace("art_", "")[:16],
        path=str(path),
        rel_path=rel_path,
        kind=kind,
        name=path.name or rel_path,
        purpose=_clean(purpose or _purpose(kind, rel_path), 240),
        provenance=_clean(provenance, 300),
        source=_clean(source, 60) or "asset-library",
        reuse_hints=_reuse_hints(kind, rel_path),
        tags=_dedupe([kind, *(tags or [])]),
        size=_size(path),
        updated_at=_mtime(path) or _now(),
    )


def _from_artifact(root: Path, artifact: artifact_studio.ArtifactRecord) -> AssetRecord:
    path = Path(artifact.path)
    kind = _kind(path) if path.suffix else artifact.kind
    return AssetRecord(
        asset_id="asset_" + artifact.artifact_id.replace("art_", "")[:16],
        path=artifact.path,
        rel_path=artifact.rel_path,
        kind=kind,
        name=artifact.name,
        purpose=_purpose(kind, artifact.rel_path),
        provenance=artifact.provenance or artifact.source,
        source="artifact-studio",
        reuse_hints=_reuse_hints(kind, artifact.rel_path),
        tags=_dedupe([kind, artifact.status, artifact.source]),
        size=artifact.size,
        updated_at=artifact.updated_at,
    )


def _walk_assets(root: Path, *, limit: int) -> list[Path]:
    out = []
    for path in root.rglob("*"):
        if len(out) >= limit:
            break
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in ASSET_EXTENSIONS:
            continue
        out.append(path.resolve())
    return out


def _read(cwd: str | Path) -> list[AssetRecord]:
    path = library_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("assets", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                AssetRecord(
                    asset_id=str(item.get("asset_id") or ""),
                    path=str(item.get("path") or ""),
                    rel_path=str(item.get("rel_path") or ""),
                    kind=str(item.get("kind") or "file"),
                    name=str(item.get("name") or ""),
                    purpose=str(item.get("purpose") or ""),
                    provenance=str(item.get("provenance") or ""),
                    source=str(item.get("source") or "asset-library"),
                    reuse_hints=[str(value) for value in item.get("reuse_hints", []) if str(value).strip()],
                    tags=[str(value) for value in item.get("tags", []) if str(value).strip()],
                    size=int(item.get("size") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.asset_id and row.path]


def _write(cwd: str | Path, records: list[AssetRecord]) -> None:
    path = library_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "assets": [record.to_dict() for record in records]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _current(record: AssetRecord) -> AssetRecord:
    path = Path(record.path)
    if not path.exists():
        return record
    return AssetRecord(**{**record.to_dict(), "size": _size(path), "updated_at": _mtime(path) or record.updated_at})


def _resolve(root: Path, path: str | Path) -> Path:
    p = Path(path).expanduser()
    return (p if p.is_absolute() else root / p).resolve()


def _kind(path: Path) -> str:
    return ASSET_EXTENSIONS.get(path.suffix.lower(), "file")


def _purpose(kind: str, rel_path: str) -> str:
    if kind == "ui":
        return "Reusable interface or website asset."
    if kind in {"image", "video", "audio"}:
        return f"Reusable {kind} media asset."
    if kind in {"document", "deck", "spreadsheet", "notes", "data"}:
        return f"Reusable {kind} knowledge asset."
    return "Reusable project asset."


def _reuse_hints(kind: str, rel_path: str) -> list[str]:
    hints = {
        "image": ["Use in hero sections, cards, screenshots, or visual QA references.", "Verify aspect ratio before reuse."],
        "video": ["Use as motion background or product demo source.", "Check file size and autoplay constraints."],
        "ui": ["Reuse as frontend pattern or generated website artifact.", "Run browser QA after changes."],
        "document": ["Use as source material or deliverable reference.", "Render/check layout before sharing."],
        "deck": ["Use as presentation source or sales collateral.", "Render slides before delivery."],
        "spreadsheet": ["Use as structured data or tracking source.", "Check formulas and columns before analysis."],
        "data": ["Use as import source for analysis or dashboards.", "Validate headers and row counts."],
        "notes": ["Use as durable context or project memory.", "Keep concise and link to source files."],
    }
    return hints.get(kind, ["Reuse only after checking provenance and current file state."])


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _mtime(path: Path) -> int:
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value, 160)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _clean(value: str, limit: int) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
