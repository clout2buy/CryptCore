"""Durable visual memory for screenshot observations and UI defects."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import browser_recorder, desktop_recorder, redact, session, settings


SCHEMA_VERSION = 1
MAX_ANNOTATIONS = 300
SEVERITIES = {"info", "warning", "high"}
STATUSES = {"needs-review", "active", "resolved", "archived"}
VISUAL_RE = re.compile(r"\b(screenshot|screen|ui|visual|layout|panel|chat|button|text|flicker|jolt|overlap|clutter|animation|responsive)\b", re.I)
DEFECT_RE = re.compile(
    r"\b(flicker(?:ing)?|jolt(?:ing)?|broken|overlap(?:ping)?|clutter(?:ed)?|trash|bad|ugly|"
    r"hard to read|too much|doesn'?t show|not rendering|cut off|misaligned)\b",
    re.I,
)


@dataclass(frozen=True)
class ScreenshotAnnotation:
    annotation_id: str
    cwd: str
    screenshot: str
    source: str
    observation: str
    defect: str = ""
    recommendation: str = ""
    severity: str = "info"
    status: str = "needs-review"
    tags: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def annotations_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "visual" / "screenshot_memory.json"


def add_annotation(
    cwd: str | Path,
    screenshot: str | Path,
    *,
    observation: str,
    source: str = "manual",
    defect: str = "",
    recommendation: str = "",
    severity: str = "info",
    status: str = "needs-review",
    tags: list[str] | None = None,
) -> ScreenshotAnnotation:
    root = Path(cwd).expanduser().resolve()
    shot = _screenshot(root, screenshot)
    clean_source = _clean(source, 180) or "manual"
    now = _now()
    existing = _existing(root, shot, clean_source)
    merged_tags = _dedupe([*(tags or []), *(existing.tags if existing else [])])
    annotation = ScreenshotAnnotation(
        annotation_id=existing.annotation_id if existing else "shot_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        screenshot=shot,
        source=clean_source,
        observation=_clean(observation, 1_200) or "Screenshot captured for visual review.",
        defect=_clean(defect, 500),
        recommendation=_clean(recommendation, 500),
        severity=_severity(severity),
        status=_status(status),
        tags=merged_tags,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    if existing and annotation == replace(existing, updated_at=annotation.updated_at):
        return existing
    rows = [row for row in list_annotations(root, include_all=True, limit=MAX_ANNOTATIONS) if row.annotation_id != annotation.annotation_id]
    rows.insert(0, annotation)
    _write(root, rows[:MAX_ANNOTATIONS])
    return annotation


def observe_feedback(cwd: str | Path, text: str, *, source: str = "chat") -> ScreenshotAnnotation | None:
    clean = _clean(text, 1_200)
    if not clean or not VISUAL_RE.search(clean):
        return None
    defect = _defect_hint(clean)
    screenshot = "chat-feedback-" + hashlib.sha256(clean.encode("utf-8", errors="replace")).hexdigest()[:10]
    return add_annotation(
        cwd,
        screenshot,
        observation=clean,
        source=source,
        defect=defect,
        recommendation=_recommendation(defect),
        severity="warning" if defect else "info",
        tags=_tags(clean, defect),
    )


def ingest_recordings(cwd: str | Path) -> list[ScreenshotAnnotation]:
    root = Path(cwd).expanduser().resolve()
    created: list[ScreenshotAnnotation] = []
    for recording in browser_recorder.list_recordings(root, include_all=True, limit=30):
        note = recording.notes[-1] if recording.notes else ""
        for screenshot in recording.screenshots:
            created.append(
                add_annotation(
                    root,
                    screenshot,
                    observation=note or f"Browser screenshot for {recording.url or recording.title or recording.recording_id}.",
                    source=f"browser:{recording.recording_id}",
                    defect=_defect_hint(" ".join(recording.console_errors + recording.notes)),
                    recommendation="Review browser screenshot, console errors, and viewport framing before shipping.",
                    severity="warning" if recording.console_errors or recording.status == "failed" else "info",
                    tags=["browser", recording.status],
                )
            )
    for recording in desktop_recorder.list_recordings(root, include_all=True, limit=30):
        note = recording.safety_notes[-1] if recording.safety_notes else ""
        for screenshot in recording.screenshots:
            created.append(
                add_annotation(
                    root,
                    screenshot,
                    observation=note or f"Desktop screenshot for {recording.title}.",
                    source=f"desktop:{recording.recording_id}",
                    defect=_defect_hint(" ".join(recording.safety_notes)),
                    recommendation="Review desktop screenshot before continuing visible operation.",
                    severity="warning" if recording.status in {"blocked", "failed"} else "info",
                    tags=["desktop", recording.status],
                )
            )
    return created


def list_annotations(cwd: str | Path, *, include_all: bool = False, limit: int = 80) -> list[ScreenshotAnnotation]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status in {"needs-review", "active"}]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    ingest_recordings(cwd)
    rows = list_annotations(cwd, include_all=True, limit=80)
    active = [row for row in rows if row.status in {"needs-review", "active"}]
    defects = [row for row in active if row.defect]
    return {
        "schema": SCHEMA_VERSION,
        "total": len(rows),
        "active": len(active),
        "defects": len(defects),
        "high": sum(1 for row in active if row.severity == "high"),
        "bySource": _counts(_source_group(row.source) for row in rows),
        "annotations": [row.to_dict() for row in rows[:20]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_annotations(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Screenshot Annotation Memory"]
    for row in rows:
        defect = f"; defect={row.defect}" if row.defect else ""
        recommendation = f"; next={row.recommendation}" if row.recommendation else ""
        lines.append(f"- {row.severity} {row.screenshot} from {row.source}: {row.observation}{defect}{recommendation}")
    lines.append("- Reuse these notes when improving UI, browser operation, screenshots, or visual QA.")
    return "\n".join(lines)


def _existing(root: Path, screenshot: str, source: str) -> ScreenshotAnnotation | None:
    return next(
        (
            row
            for row in list_annotations(root, include_all=True, limit=MAX_ANNOTATIONS)
            if row.screenshot == screenshot and row.source == source
        ),
        None,
    )


def _read(cwd: str | Path) -> list[ScreenshotAnnotation]:
    path = annotations_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("annotations", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                ScreenshotAnnotation(
                    annotation_id=str(item.get("annotation_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    screenshot=str(item.get("screenshot") or ""),
                    source=str(item.get("source") or "manual"),
                    observation=str(item.get("observation") or ""),
                    defect=str(item.get("defect") or ""),
                    recommendation=str(item.get("recommendation") or ""),
                    severity=_severity(str(item.get("severity") or "info")),
                    status=_status(str(item.get("status") or "needs-review")),
                    tags=[_clean(str(tag), 80) for tag in item.get("tags", []) if str(tag).strip()],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.annotation_id and row.cwd]


def _write(cwd: str | Path, rows: list[ScreenshotAnnotation]) -> None:
    path = annotations_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "annotations": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _screenshot(root: Path, value: str | Path) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown-screenshot"
    path = Path(raw)
    try:
        if path.is_absolute():
            return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())
    return raw.replace("\\", "/")


def _defect_hint(text: str) -> str:
    match = DEFECT_RE.search(text)
    return _clean(match.group(0), 120) if match else ""


def _recommendation(defect: str) -> str:
    if not defect:
        return "Keep this as visual context for the next UI/browser pass."
    lower = defect.lower()
    if "flicker" in lower or "jolt" in lower or "not rendering" in lower:
        return "Check live event rendering, layout reflow, and polling refresh paths."
    if "overlap" in lower or "cut off" in lower or "misaligned" in lower:
        return "Inspect responsive bounds, fixed dimensions, and text overflow."
    if "clutter" in lower or "too much" in lower:
        return "Simplify the visible surface and move secondary controls into progressive disclosure."
    return "Reproduce visually, patch the smallest UI cause, then verify with a screenshot."


def _tags(text: str, defect: str) -> list[str]:
    tags = ["visual"]
    lower = text.lower()
    if "chat" in lower:
        tags.append("chat")
    if "ui" in lower or "panel" in lower:
        tags.append("ui")
    if "screenshot" in lower or "screen" in lower:
        tags.append("screenshot")
    if defect:
        tags.append("defect")
    return tags


def _source_group(source: str) -> str:
    return str(source or "manual").split(":", 1)[0]


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _severity(value: str) -> str:
    clean = str(value or "info").strip().lower()
    return clean if clean in SEVERITIES else "info"


def _status(value: str) -> str:
    clean = str(value or "needs-review").strip().lower()
    return clean if clean in STATUSES else "needs-review"


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value, 80)
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
