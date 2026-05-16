"""Durable memory for recurring tool failures and recovery hints."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import redact, session, settings


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ToolFailurePattern:
    signature: str
    tool: str
    kind: str
    count: int = 0
    first_seen: int = 0
    last_seen: int = 0
    last_error: str = ""
    last_args: str = ""
    recovery_hint: str = ""
    successful_recoveries: int = 0
    last_success_at: int = 0
    recovery_pattern: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def memory_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "tool_failure_memory" / "patterns.json"


def record_event(cwd: str | Path, event: dict[str, Any]) -> ToolFailurePattern | None:
    if str(event.get("event") or "") != "toolResult":
        return None
    tool = _clean(str(event.get("tool") or "tool"), 80)
    if event.get("ok") is True:
        return record_success(cwd, tool=tool, result_text=str(event.get("text") or ""))
    return record_failure(
        cwd,
        tool=tool,
        error_text=str(event.get("text") or event.get("error") or ""),
        args=event.get("args") if isinstance(event.get("args"), dict) else {},
    )


def record_failure(cwd: str | Path, *, tool: str, error_text: str, args: dict[str, Any] | None = None) -> ToolFailurePattern:
    now = int(time.time())
    tool = _clean(tool or "tool", 80)
    kind = classify(error_text)
    signature = signature_for(tool, kind, error_text)
    patterns = {pattern.signature: pattern for pattern in list_patterns(cwd, limit=500)}
    existing = patterns.get(signature)
    pattern = ToolFailurePattern(
        signature=signature,
        tool=tool,
        kind=kind,
        count=(existing.count if existing else 0) + 1,
        first_seen=existing.first_seen if existing else now,
        last_seen=now,
        last_error=_clean(error_text, 700),
        last_args=_clean(json.dumps(redact.content(args or {}), ensure_ascii=False, sort_keys=True), 500),
        recovery_hint=recovery_hint(kind, error_text),
        successful_recoveries=existing.successful_recoveries if existing else 0,
        last_success_at=existing.last_success_at if existing else 0,
        recovery_pattern=existing.recovery_pattern if existing else "",
    )
    patterns[signature] = pattern
    _write_patterns(cwd, patterns.values())
    return pattern


def record_success(cwd: str | Path, *, tool: str, result_text: str = "") -> ToolFailurePattern | None:
    now = int(time.time())
    tool = _clean(tool or "tool", 80)
    patterns = list_patterns(cwd, limit=500)
    unresolved = [
        pattern
        for pattern in patterns
        if pattern.tool == tool and pattern.last_seen > pattern.last_success_at
    ]
    if not unresolved:
        return None
    target = sorted(unresolved, key=lambda pattern: (pattern.last_seen, pattern.count), reverse=True)[0]
    updated = ToolFailurePattern(
        **{
            **target.to_dict(),
            "successful_recoveries": target.successful_recoveries + 1,
            "last_success_at": now,
            "recovery_pattern": _clean(result_text or f"{tool} succeeded after {target.kind} failure.", 500),
        }
    )
    by_sig = {pattern.signature: pattern for pattern in patterns}
    by_sig[target.signature] = updated
    _write_patterns(cwd, by_sig.values())
    return updated


def list_patterns(cwd: str | Path, *, limit: int = 50) -> list[ToolFailurePattern]:
    data = _read(cwd)
    patterns = []
    for item in data.get("patterns", []):
        if not isinstance(item, dict):
            continue
        try:
            patterns.append(
                ToolFailurePattern(
                    signature=str(item.get("signature") or ""),
                    tool=str(item.get("tool") or "tool"),
                    kind=str(item.get("kind") or "unknown"),
                    count=int(item.get("count") or 0),
                    first_seen=int(item.get("first_seen") or 0),
                    last_seen=int(item.get("last_seen") or 0),
                    last_error=str(item.get("last_error") or ""),
                    last_args=str(item.get("last_args") or ""),
                    recovery_hint=str(item.get("recovery_hint") or ""),
                    successful_recoveries=int(item.get("successful_recoveries") or 0),
                    last_success_at=int(item.get("last_success_at") or 0),
                    recovery_pattern=str(item.get("recovery_pattern") or ""),
                )
            )
        except Exception:
            continue
    patterns = [pattern for pattern in patterns if pattern.signature]
    patterns.sort(key=lambda pattern: (pattern.count, pattern.last_seen), reverse=True)
    return patterns[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    patterns = list_patterns(cwd, limit=80)
    recurring = [pattern for pattern in patterns if pattern.count >= 2]
    recovered = [pattern for pattern in patterns if pattern.successful_recoveries]
    return {
        "total": len(patterns),
        "recurring": len(recurring),
        "recovered": len(recovered),
        "latest": max((pattern.last_seen for pattern in patterns), default=0),
        "patterns": [pattern.to_dict() for pattern in patterns[:20]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    patterns = list_patterns(cwd, limit=limit)
    if not patterns:
        return ""
    lines = ["# Tool Failure Memory"]
    lines.append("- Before retrying a failed tool, compare the error to these signatures and change strategy instead of repeating it.")
    for pattern in patterns:
        if pattern.count <= 0:
            continue
        recovery = pattern.recovery_pattern or pattern.recovery_hint
        lines.append(
            f"- {pattern.tool}/{pattern.kind} x{pattern.count}: {pattern.last_error[:180]}; recovery={recovery[:180]}"
        )
    return "\n".join(lines)


def classify(error_text: str) -> str:
    lowered = str(error_text or "").lower()
    if "schema validation failed" in lowered or "expected a non-empty array" in lowered:
        return "schema_validation"
    if "read-before-edit" in lowered or "partial range was read" in lowered:
        return "read_before_edit"
    if "permissionerror" in lowered or "permission denied" in lowered or "access is denied" in lowered:
        return "permission"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "jsondecodeerror" in lowered or "invalid json" in lowered:
        return "invalid_json"
    if "not found" in lowered or "no such file" in lowered or "cannot find" in lowered:
        return "missing_target"
    if "approval" in lowered and ("denied" in lowered or "required" in lowered):
        return "approval_gate"
    if "rate limit" in lowered or "429" in lowered:
        return "rate_limit"
    return "unknown"


def recovery_hint(kind: str, error_text: str = "") -> str:
    hints = {
        "schema_validation": "Read the exact schema and retry with concrete non-empty required fields.",
        "read_before_edit": "Read the full target file or exact required context, then make one concrete edit.",
        "permission": "Verify the resolved path and permission boundary before retrying the write.",
        "timeout": "Split the work, inspect logs/state, and retry with a smaller focused command.",
        "invalid_json": "Read raw content, preserve a backup, and repair through a parser instead of string guessing.",
        "missing_target": "Re-list files or refresh workspace state before retrying the target path.",
        "approval_gate": "Stop and surface the exact external/destructive action for approval.",
        "rate_limit": "Back off, use a cheaper/fallback provider, or batch fewer calls.",
        "unknown": "Summarize the failure, inspect current state, and retry once with a changed plan.",
    }
    return hints.get(kind, hints["unknown"])


def signature_for(tool: str, kind: str, error_text: str) -> str:
    canonical = _canonical_error(error_text)
    digest = hashlib.sha1(f"{tool}\0{kind}\0{canonical[:260]}".encode("utf-8", errors="replace")).hexdigest()
    return f"{tool}:{kind}:{digest[:16]}"


def _canonical_error(error_text: str) -> str:
    text = redact.text(str(error_text or "")).lower()
    text = re.sub(r"[a-z]:[\\/][^\s]+", "<path>", text)
    text = re.sub(r"/[^\s]+", "<path>", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", text)
    text = re.sub(r"\b\d+\b", "<n>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _read(cwd: str | Path) -> dict[str, Any]:
    path = memory_path(cwd)
    if not path.exists():
        return {"schema": SCHEMA_VERSION, "patterns": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {"schema": SCHEMA_VERSION, "patterns": []}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return {"schema": SCHEMA_VERSION, "patterns": []}
    return data


def _write_patterns(cwd: str | Path, patterns: Any) -> None:
    path = memory_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(list(patterns), key=lambda pattern: (pattern.count, pattern.last_seen), reverse=True)[:200]
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "patterns": [pattern.to_dict() for pattern in rows]}, indent=2),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _clean(value: str, limit: int) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
