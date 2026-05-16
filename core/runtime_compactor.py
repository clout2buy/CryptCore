"""Compact bulky runtime snapshots into stable summaries."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import session, settings


SCHEMA_VERSION = 1
IMPORTANT_KEYS = (
    "workspace",
    "provider",
    "model",
    "authOk",
    "approval",
    "thinkingMode",
    "activeTask",
    "webui",
    "providerHealth",
    "onboarding",
    "repairDoctor",
    "chaosChecks",
    "releaseCandidate",
    "dailyBrief",
    "missionWorkers",
    "jobQueue",
    "liveReplay",
    "notifications",
    "capabilityMatrix",
)


@dataclass(frozen=True)
class CompactRuntime:
    schema: int
    total_keys: int
    estimated_chars: int
    compact_chars: int
    compression_ratio: float
    summary: dict[str, Any]
    counts: dict[str, int]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "totalKeys": self.total_keys,
            "estimatedChars": self.estimated_chars,
            "compactChars": self.compact_chars,
            "compressionRatio": self.compression_ratio,
            "summary": self.summary,
            "counts": self.counts,
            "warnings": self.warnings,
        }


def compact(runtime_snapshot: dict[str, Any], *, max_list_items: int = 5) -> dict[str, Any]:
    snap = runtime_snapshot if isinstance(runtime_snapshot, dict) else {}
    estimated = len(json.dumps(snap, default=str, ensure_ascii=False))
    counts = _counts(snap)
    summary = {key: _compact_value(snap.get(key), max_list_items=max_list_items) for key in IMPORTANT_KEYS if key in snap}
    warnings = _warnings(snap)
    compacted = CompactRuntime(
        schema=SCHEMA_VERSION,
        total_keys=len(snap),
        estimated_chars=estimated,
        compact_chars=0,
        compression_ratio=1.0,
        summary=summary,
        counts=counts,
        warnings=warnings,
    )
    data = compacted.to_dict()
    compact_chars = len(json.dumps(data, default=str, ensure_ascii=False))
    ratio = round(compact_chars / max(1, estimated), 3)
    return {
        **data,
        "compactChars": compact_chars,
        "compressionRatio": ratio,
    }


def write_compact(cwd: str | Path, runtime_snapshot: dict[str, Any]) -> dict[str, Any]:
    data = compact(runtime_snapshot)
    path = compact_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    settings.restrict_file_permissions(path)
    return {**data, "path": str(path)}


def compact_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "runtime" / "compact_snapshot.json"


def prompt_section(runtime_snapshot: dict[str, Any]) -> str:
    data = compact(runtime_snapshot)
    lines = [
        "# Runtime State Compact",
        f"- keys={data['totalKeys']} size={data['compactChars']}/{data['estimatedChars']} chars ratio={data['compressionRatio']}",
    ]
    for warning in data["warnings"][:6]:
        lines.append(f"- warning={warning}")
    return "\n".join(lines)


def _compact_value(value: Any, *, max_list_items: int) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"messages", "items", "events", "logs", "checks", "scores", "workers", "jobs", "cards", "steps", "scenarios"}:
                out[key] = _compact_list(item, max_list_items=max_list_items)
            elif isinstance(item, (dict, list)):
                out[key] = _compact_value(item, max_list_items=max_list_items)
            else:
                out[key] = item
        return out
    if isinstance(value, list):
        return _compact_list(value, max_list_items=max_list_items)
    return value


def _compact_list(value: Any, *, max_list_items: int) -> dict[str, Any]:
    rows = value if isinstance(value, list) else []
    preview = []
    for item in rows[: max(1, max_list_items)]:
        if isinstance(item, dict):
            preview.append(_small_dict(item))
        else:
            preview.append(str(item)[:160])
    return {"count": len(rows), "preview": preview}


def _small_dict(item: dict[str, Any]) -> dict[str, Any]:
    preferred = (
        "id",
        "name",
        "title",
        "label",
        "status",
        "state",
        "severity",
        "detail",
        "summary",
        "text",
        "updated_at",
        "created_at",
    )
    out = {key: item[key] for key in preferred if key in item and item[key] not in (None, "")}
    if not out:
        for key, value in list(item.items())[:4]:
            out[str(key)] = value
    return {key: (str(value)[:220] if isinstance(value, str) else value) for key, value in out.items()}


def _counts(snap: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, value in snap.items():
        if isinstance(value, list):
            counts[key] = len(value)
        elif isinstance(value, dict):
            for count_key in ("total", "count", "active", "failing", "unread", "ready", "needsAuth"):
                if count_key in value and isinstance(value[count_key], (int, float)):
                    counts[f"{key}.{count_key}"] = int(value[count_key])
    return counts


def _warnings(snap: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    repair = snap.get("repairDoctor") if isinstance(snap.get("repairDoctor"), dict) else {}
    if int(repair.get("failing") or 0):
        warnings.append(f"repair doctor has {repair.get('failing')} failing item(s)")
    chaos = snap.get("chaosChecks") if isinstance(snap.get("chaosChecks"), dict) else {}
    if chaos.get("status") and chaos.get("status") != "pass":
        warnings.append(f"chaos checks status is {chaos.get('status')}")
    notifications = snap.get("notifications") if isinstance(snap.get("notifications"), dict) else {}
    if int(notifications.get("critical") or 0):
        warnings.append(f"{notifications.get('critical')} critical notification(s)")
    jobs = snap.get("jobQueue") if isinstance(snap.get("jobQueue"), dict) else {}
    if int(jobs.get("interrupted") or 0):
        warnings.append(f"{jobs.get('interrupted')} interrupted job(s)")
    return warnings
