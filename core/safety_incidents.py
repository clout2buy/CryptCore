"""Durable safety incident log for blocked, risky, and denied actions."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import secret_hygiene, session, settings


SCHEMA_VERSION = 1
KINDS = {"secret-detected", "dangerous-prompt", "approval-denied", "blocked-action", "policy"}
SEVERITIES = {"info", "warning", "high", "critical"}
STATUSES = {"open", "reviewed", "ignored"}
DANGEROUS_RE = re.compile(
    r"\b(reset\s+--hard|rm\s+-rf|format\s+(?:drive|disk)|drop\s+table|wipe\s+(?:drive|disk|repo)|"
    r"steal|exfiltrate|bypass\s+(?:auth|login|security)|disable\s+(?:logs|audit)|malware|keylogger|dox)\b",
    re.I,
)


@dataclass(frozen=True)
class SafetyIncident:
    incident_id: str
    cwd: str
    kind: str
    severity: str
    title: str
    detail: str = ""
    source: str = "runtime"
    related_id: str = ""
    status: str = "open"
    tags: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def incidents_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "safety" / "incidents.json"


def record(
    cwd: str | Path,
    *,
    kind: str,
    title: str,
    severity: str = "warning",
    detail: str = "",
    source: str = "runtime",
    related_id: str = "",
    tags: list[str] | None = None,
) -> SafetyIncident:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    incident = SafetyIncident(
        incident_id="incident_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        kind=_kind(kind),
        severity=_severity(severity),
        title=_clean(title, 180) or "Safety incident",
        detail=_clean(detail, 1_000),
        source=_clean(source, 80) or "runtime",
        related_id=_clean(related_id, 120),
        status="open",
        tags=_dedupe(tags or []),
        created_at=now,
        updated_at=now,
    )
    rows = list_incidents(root, include_all=True)
    rows.insert(0, incident)
    _write(root, rows[:500])
    return incident


def observe_prompt(cwd: str | Path, text: str, *, source: str = "webui") -> list[SafetyIncident]:
    clean = _clean(text, 2_000)
    if not clean:
        return []
    incidents = []
    findings = secret_hygiene.scan_text(clean, file="prompt")
    if findings:
        kinds = sorted({finding.kind for finding in findings})
        incidents.append(
            record(
                cwd,
                kind="secret-detected",
                severity="critical",
                title="Secret-looking text detected in prompt",
                detail=f"Detected: {', '.join(kinds)}",
                source=source,
                tags=["secret", *kinds],
            )
        )
    match = DANGEROUS_RE.search(clean)
    if match:
        incidents.append(
            record(
                cwd,
                kind="dangerous-prompt",
                severity="critical",
                title="Dangerous operation requested",
                detail=f"Matched risky phrase: {match.group(0)}",
                source=source,
                tags=["dangerous", "policy"],
            )
        )
    return incidents


def mark_status(cwd: str | Path, incident_id: str, *, status: str) -> SafetyIncident:
    root = Path(cwd).expanduser().resolve()
    rows = []
    updated: SafetyIncident | None = None
    for incident in list_incidents(root, include_all=True):
        if incident.incident_id != incident_id:
            rows.append(incident)
            continue
        updated = replace(incident, status=_status(status), updated_at=_now())
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown safety incident: {incident_id}")
    _write(root, rows)
    return updated


def list_incidents(cwd: str | Path, *, include_all: bool = False, limit: int = 80) -> list[SafetyIncident]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status == "open"]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_incidents(cwd, include_all=True, limit=80)
    open_rows = [row for row in rows if row.status == "open"]
    return {
        "total": len(rows),
        "open": len(open_rows),
        "critical": sum(1 for row in open_rows if row.severity == "critical"),
        "byKind": _counts(row.kind for row in rows),
        "incidents": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_incidents(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Safety Incident Log"]
    for row in rows:
        lines.append(f"- {row.severity} {row.kind}: {row.title}; {row.detail}")
    lines.append("- Treat repeated incidents as policy feedback; avoid retrying blocked or denied actions without a changed user instruction.")
    return "\n".join(lines)


def _read(cwd: str | Path) -> list[SafetyIncident]:
    path = incidents_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("incidents", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                SafetyIncident(
                    incident_id=str(item.get("incident_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    kind=_kind(str(item.get("kind") or "policy")),
                    severity=_severity(str(item.get("severity") or "warning")),
                    title=str(item.get("title") or ""),
                    detail=str(item.get("detail") or ""),
                    source=str(item.get("source") or "runtime"),
                    related_id=str(item.get("related_id") or ""),
                    status=_status(str(item.get("status") or "open")),
                    tags=[str(tag) for tag in item.get("tags", []) if str(tag).strip()],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.incident_id and row.cwd]


def _write(cwd: str | Path, rows: list[SafetyIncident]) -> None:
    path = incidents_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "incidents": [row.to_dict() for row in rows]}, indent=2),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _kind(value: str) -> str:
    clean = str(value or "policy").strip().lower()
    return clean if clean in KINDS else "policy"


def _severity(value: str) -> str:
    clean = str(value or "warning").strip().lower()
    return clean if clean in SEVERITIES else "warning"


def _status(value: str) -> str:
    clean = str(value or "open").strip().lower()
    return clean if clean in STATUSES else "open"


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
        clean = _clean(value, 80)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
