"""Release screenshot planning and artifact attachment."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import artifact_studio, session, settings


SCHEMA_VERSION = 1
DEFAULT_URL = "http://127.0.0.1:8765/"
DEFAULT_VIEWPORTS = (
    ("desktop", 1440, 960),
    ("mobile", 390, 844),
)


@dataclass(frozen=True)
class ScreenshotTarget:
    name: str
    url: str
    width: int
    height: int
    path: str
    status: str = "planned"
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScreenshotManifest:
    schema: int
    release_id: str
    cwd: str
    output_dir: str
    created_at: int
    updated_at: int
    targets: list[ScreenshotTarget] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan(
    cwd: str | Path,
    *,
    release_id: str = "",
    output_dir: str | Path | None = None,
    url: str = DEFAULT_URL,
    viewports: list[tuple[str, int, int]] | None = None,
) -> ScreenshotManifest:
    root = Path(cwd).expanduser().resolve()
    out_dir = _output_dir(root, release_id=release_id, output_dir=output_dir)
    shots_dir = out_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    now = _now()
    targets = []
    for name, width, height in viewports or list(DEFAULT_VIEWPORTS):
        safe = _safe_name(name)
        path = shots_dir / f"{safe}-{int(width)}x{int(height)}.png"
        targets.append(
            ScreenshotTarget(
                name=safe,
                url=_clean_url(url),
                width=max(1, int(width)),
                height=max(1, int(height)),
                path=str(path),
                status="captured" if _is_image(path) else "planned",
                notes=_notes(path),
            )
        )
    existing = _read(out_dir)
    created_at = existing.created_at if existing else now
    manifest = ScreenshotManifest(
        schema=SCHEMA_VERSION,
        release_id=_clean_release_id(release_id) or (existing.release_id if existing else "manual"),
        cwd=str(root),
        output_dir=str(out_dir),
        created_at=created_at,
        updated_at=now,
        targets=targets,
    )
    _write(root, manifest)
    return manifest


def register(
    cwd: str | Path,
    image_path: str | Path,
    *,
    release_id: str = "",
    output_dir: str | Path | None = None,
    viewport: str = "",
    url: str = DEFAULT_URL,
    note: str = "",
) -> ScreenshotManifest:
    root = Path(cwd).expanduser().resolve()
    out_dir = _output_dir(root, release_id=release_id, output_dir=output_dir)
    manifest = _read(out_dir) or plan(root, release_id=release_id, output_dir=out_dir, url=url)
    image = Path(image_path).expanduser().resolve()
    if not _is_image(image):
        raise ValueError(f"screenshot image does not exist or is unsupported: {image}")
    artifact = artifact_studio.record_artifact(
        root,
        image,
        kind="screenshot",
        status="verified",
        source="release-screenshot-pipeline",
        provenance=f"release {manifest.release_id} screenshot",
        note=note or "release screenshot captured",
    )
    name = _safe_name(viewport or image.stem)
    target = ScreenshotTarget(
        name=name,
        url=_clean_url(url),
        width=0,
        height=0,
        path=artifact.path,
        status="captured",
        notes=[note or "registered release screenshot"],
    )
    targets = [row for row in manifest.targets if row.name != name and Path(row.path).resolve() != image]
    targets.insert(0, target)
    updated = replace(manifest, updated_at=_now(), targets=targets)
    _write(root, updated)
    return updated


def checklist_items(cwd: str | Path, *, output_dir: str | Path | None = None) -> list[str]:
    manifest = _read(_output_dir(Path(cwd).expanduser().resolve(), output_dir=output_dir))
    if manifest is None:
        return []
    return [_format_target(target) for target in manifest.targets]


def captured_count(cwd: str | Path, *, output_dir: str | Path | None = None) -> int:
    manifest = _read(_output_dir(Path(cwd).expanduser().resolve(), output_dir=output_dir))
    if manifest is None:
        return 0
    return sum(1 for target in manifest.targets if target.status == "captured" and _is_image(Path(target.path)))


def manifest_path(output_dir: str | Path) -> Path:
    return Path(output_dir).expanduser().resolve() / "screenshot-plan.json"


def _write(cwd: Path, manifest: ScreenshotManifest) -> None:
    out_dir = Path(manifest.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = manifest_path(out_dir)
    md_path = out_dir / "screenshot-plan.md"
    json_path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(_format_manifest(manifest) + "\n", encoding="utf-8")
    settings.restrict_file_permissions(json_path)
    settings.restrict_file_permissions(md_path)
    artifact_studio.record_artifact(
        cwd,
        md_path,
        kind="document",
        status="ready",
        source="release-screenshot-pipeline",
        provenance=f"release {manifest.release_id} screenshot plan",
        note="release screenshot plan",
        attach_recent=False,
    )


def _read(output_dir: str | Path) -> ScreenshotManifest | None:
    path = manifest_path(output_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return None
    try:
        targets = [
            ScreenshotTarget(
                name=str(item.get("name") or ""),
                url=str(item.get("url") or DEFAULT_URL),
                width=int(item.get("width") or 0),
                height=int(item.get("height") or 0),
                path=str(item.get("path") or ""),
                status=_status(str(item.get("status") or "")),
                notes=[str(note) for note in item.get("notes", []) if str(note).strip()],
            )
            for item in data.get("targets", [])
            if isinstance(item, dict)
        ]
        return ScreenshotManifest(
            schema=SCHEMA_VERSION,
            release_id=str(data.get("release_id") or "manual"),
            cwd=str(data.get("cwd") or ""),
            output_dir=str(data.get("output_dir") or output_dir),
            created_at=int(data.get("created_at") or 0),
            updated_at=int(data.get("updated_at") or 0),
            targets=targets,
        )
    except Exception:
        return None


def _format_manifest(manifest: ScreenshotManifest) -> str:
    lines = [
        f"# Release Screenshot Plan {manifest.release_id}",
        "",
        f"- Workspace: {manifest.cwd}",
        f"- Output: {manifest.output_dir}",
        "",
        "## Targets",
    ]
    lines.extend(f"- {_format_target(target)}" for target in manifest.targets)
    lines.extend(
        [
            "",
            "## Capture",
            "- Open the WebUI or release target.",
            "- Capture every planned viewport before marking a UI-heavy release ready.",
            "- Register final screenshots so they appear in the artifact studio and release checklist.",
        ]
    )
    return "\n".join(lines)


def _format_target(target: ScreenshotTarget) -> str:
    size = f"{target.width}x{target.height}" if target.width and target.height else "registered"
    return f"{target.status.upper()} {target.name} {size} {target.url} -> {target.path}"


def _output_dir(root: Path, *, release_id: str = "", output_dir: str | Path | None = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    release = _clean_release_id(release_id) or "manual"
    return session.project_dir(root) / "release" / "screenshots" / release


def _is_image(path: Path) -> bool:
    return path.exists() and path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def _notes(path: Path) -> list[str]:
    if _is_image(path):
        return ["image present"]
    return ["capture pending"]


def _status(value: str) -> str:
    clean = str(value or "planned").strip().lower()
    return clean if clean in {"planned", "captured", "failed"} else "planned"


def _clean_url(url: str) -> str:
    clean = " ".join(str(url or DEFAULT_URL).split())
    return clean[:500] if clean else DEFAULT_URL


def _clean_release_id(value: str) -> str:
    return _safe_name(value)[:80]


def _safe_name(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "").strip())
    clean = "-".join(part for part in clean.split("-") if part)
    return clean or "screenshot"


def _now() -> int:
    return int(time.time())
