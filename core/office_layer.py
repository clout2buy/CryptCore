"""Office artifact registry for documents, spreadsheets, decks, and PDFs."""
from __future__ import annotations

import csv
import json
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import artifact_studio, redact, session, settings


SCHEMA_VERSION = 1
SUPPORTED_SUFFIXES = {
    ".docx": "document",
    ".md": "document",
    ".txt": "document",
    ".pdf": "pdf",
    ".xlsx": "spreadsheet",
    ".csv": "spreadsheet",
    ".pptx": "deck",
}


@dataclass(frozen=True)
class OfficeArtifact:
    office_id: str
    path: str
    rel_path: str
    kind: str
    title: str
    purpose: str = ""
    status: str = "ready"
    preview: str = ""
    checks: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def registry_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "office" / "artifacts.json"


def create_markdown_brief(
    cwd: str | Path,
    title: str,
    sections: dict[str, str],
    *,
    folder: str = "office",
    purpose: str = "",
) -> OfficeArtifact:
    root = Path(cwd).expanduser().resolve()
    safe_title = _safe_filename(title)
    path = root / folder / f"{safe_title}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {_clean(title, 160)}", ""]
    for heading, body in sections.items():
        clean_heading = _clean(heading, 120)
        if not clean_heading:
            continue
        lines.extend([f"## {clean_heading}", "", _clean(body, 4_000), ""])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return register(root, path, purpose=purpose or "markdown brief")


def register(cwd: str | Path, path: str | Path, *, purpose: str = "", title: str = "") -> OfficeArtifact:
    root = Path(cwd).expanduser().resolve()
    office_path = _resolve(root, path)
    kind = _kind(office_path)
    if not kind:
        raise ValueError(f"unsupported office artifact type: {office_path.suffix}")
    now = _now()
    existing = _existing_for_path(root, office_path)
    checks = verify_file(office_path)
    status = "verified" if checks and all(check.startswith("PASS") for check in checks) else "failed"
    preview = preview_for_path(office_path)
    record = OfficeArtifact(
        office_id=existing.office_id if existing else "office_" + uuid.uuid4().hex[:10],
        path=str(office_path),
        rel_path=_rel(root, office_path),
        kind=kind,
        title=_clean(title or _title_from_path(office_path), 160),
        purpose=_clean(purpose or (existing.purpose if existing else ""), 500),
        status=status,
        preview=preview,
        checks=checks,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    rows = [item for item in list_artifacts(root, include_all=True) if item.office_id != record.office_id]
    rows.insert(0, record)
    _write(root, rows)
    artifact_studio.record_artifact(
        root,
        office_path,
        kind=kind,
        status=status,
        source="office-layer",
        provenance=record.purpose or f"{kind} artifact",
        preview=preview,
        note="office artifact registered",
    )
    return record


def update_status(cwd: str | Path, office_id: str, *, status: str, note: str = "") -> OfficeArtifact:
    root = Path(cwd).expanduser().resolve()
    rows = []
    updated: OfficeArtifact | None = None
    for item in list_artifacts(root, include_all=True):
        if item.office_id != office_id:
            rows.append(item)
            continue
        updated = replace(
            item,
            status=_status(status),
            checks=[*item.checks, _clean(note, 500)] if note else item.checks,
            updated_at=_now(),
        )
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown office artifact: {office_id}")
    _write(root, rows)
    return updated


def list_artifacts(cwd: str | Path, *, include_all: bool = False, limit: int = 80) -> list[OfficeArtifact]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status in {"ready", "verified", "failed"}]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_artifacts(cwd, include_all=True, limit=40)
    return {
        "total": len(rows),
        "verified": sum(1 for row in rows if row.status == "verified"),
        "failed": sum(1 for row in rows if row.status == "failed"),
        "byKind": _counts(row.kind for row in rows),
        "artifacts": [row.to_dict() for row in rows[:10]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_artifacts(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Office Artifacts"]
    for row in rows:
        lines.append(f"- {row.kind}/{row.status}: {row.title} ({row.rel_path}); {row.preview[:220]}")
    return "\n".join(lines)


def verify_file(path: str | Path) -> list[str]:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ["FAIL file missing"]
    suffix = p.suffix.lower()
    try:
        if suffix == ".pdf":
            return ["PASS pdf header"] if p.read_bytes()[:5] == b"%PDF-" else ["FAIL pdf header missing"]
        if suffix == ".docx":
            return _verify_zip_member(p, "word/document.xml", "docx document body")
        if suffix == ".xlsx":
            return _verify_zip_member(p, "xl/workbook.xml", "xlsx workbook")
        if suffix == ".pptx":
            return _verify_zip_member(p, "ppt/presentation.xml", "pptx presentation")
        if suffix == ".csv":
            with p.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                rows = list(csv.reader(handle))
            return ["PASS csv rows"] if rows else ["FAIL csv is empty"]
        if suffix in {".md", ".txt"}:
            return ["PASS text content"] if p.read_text(encoding="utf-8", errors="replace").strip() else ["FAIL text is empty"]
    except (OSError, zipfile.BadZipFile, UnicodeError, csv.Error) as exc:
        return [f"FAIL {type(exc).__name__}: {_clean(str(exc), 160)}"]
    return ["FAIL unsupported type"]


def preview_for_path(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        return "File missing."
    suffix = p.suffix.lower()
    if suffix in {".md", ".txt", ".csv"}:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "Preview unavailable."
        return _clean(text, 900)
    if suffix in {".docx", ".xlsx", ".pptx"}:
        return _zip_preview(p)
    if suffix == ".pdf":
        return f"PDF artifact ({_size_label(p)})."
    return f"{_kind(p).title() if _kind(p) else 'Office'} artifact ({_size_label(p)})."


def _verify_zip_member(path: Path, member: str, label: str) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        checks = ["PASS zip package"]
        checks.append(f"PASS {label}" if member in names else f"FAIL missing {member}")
        checks.append("PASS content types" if "[Content_Types].xml" in names else "FAIL missing [Content_Types].xml")
        return checks


def _zip_preview(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            names = sorted(zf.namelist())[:12]
    except (OSError, zipfile.BadZipFile):
        return "Office package preview unavailable."
    return f"Office package ({_size_label(path)}): " + ", ".join(names)


def _read(cwd: str | Path) -> list[OfficeArtifact]:
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
    for item in data.get("artifacts", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                OfficeArtifact(
                    office_id=str(item.get("office_id") or ""),
                    path=str(item.get("path") or ""),
                    rel_path=str(item.get("rel_path") or ""),
                    kind=str(item.get("kind") or ""),
                    title=str(item.get("title") or ""),
                    purpose=str(item.get("purpose") or ""),
                    status=_status(str(item.get("status") or "ready")),
                    preview=str(item.get("preview") or ""),
                    checks=[str(check) for check in item.get("checks", []) if str(check).strip()],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.office_id and row.path]


def _write(cwd: str | Path, rows: list[OfficeArtifact]) -> None:
    path = registry_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "artifacts": [row.to_dict() for row in rows[:200]]}, indent=2),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _existing_for_path(cwd: Path, path: Path) -> OfficeArtifact | None:
    return next((item for item in list_artifacts(cwd, include_all=True) if item.path == str(path)), None)


def _resolve(root: Path, path: str | Path) -> Path:
    p = Path(path).expanduser()
    return (p if p.is_absolute() else root / p).resolve()


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _kind(path: Path) -> str:
    return SUPPORTED_SUFFIXES.get(path.suffix.lower(), "")


def _status(value: str) -> str:
    clean = str(value or "ready").strip().lower()
    return clean if clean in {"ready", "verified", "failed", "archived"} else "ready"


def _title_from_path(path: Path) -> str:
    return path.stem.replace("-", " ").replace("_", " ").strip().title() or path.name


def _safe_filename(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "").strip())
    clean = "-".join(part for part in clean.split("-") if part)
    return clean[:80] or "office-artifact"


def _clean(value: str, limit: int = 1_000) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean[:limit]


def _size_label(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "unknown size"
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.1f} KB"
    return f"{size} B"


def _counts(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        out[key] = out.get(key, 0) + 1
    return out


def _now() -> int:
    return int(time.time())
