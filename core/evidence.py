"""Runtime evidence ledger for Crypt task claims and verification.

The ledger is intentionally small and in-memory. Session/tracing persistence
already exists elsewhere; this module gives the loop, tools, agents, and tests
a shared source of truth for what actually happened during the current run.
"""
from __future__ import annotations

import itertools
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import redact, settings


VERIFICATION_STATUSES = {"PASS", "FAIL", "PARTIAL", "SKIPPED"}
_CHECK_COMMAND_RE = re.compile(
    r"\b(pytest|unittest|tox|nox|ruff|mypy|pyright|tsc|eslint|vitest|jest|npm\s+test|pnpm\s+test|yarn\s+test|cargo\s+test|go\s+test)\b",
    re.I,
)


@dataclass(frozen=True)
class EvidenceEntry:
    id: str
    kind: str
    source: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    task_id: str | None = None


@dataclass(frozen=True)
class AuditEntry:
    audit_id: str
    phase: str
    source: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class VerificationResult:
    status: str
    commands: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    risk: str = ""
    task_id: str | None = None

    def __post_init__(self) -> None:
        status = self.status.upper()
        if status not in VERIFICATION_STATUSES:
            raise ValueError(f"unknown verification status: {self.status!r}")
        object.__setattr__(self, "status", status)


_LOCK = threading.RLock()
_COUNTER = itertools.count(1)
_ENTRIES: list[EvidenceEntry] = []


def clear() -> None:
    with _LOCK:
        _ENTRIES.clear()


def audit_dir() -> Path:
    return settings.APP_DIR / "audit"


def audit_path() -> Path:
    return audit_dir() / "audit.jsonl"


def record(
    kind: str,
    source: str,
    summary: str,
    *,
    details: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> EvidenceEntry:
    entry = EvidenceEntry(
        id=f"ev_{next(_COUNTER):06d}",
        kind=str(kind or "event"),
        source=str(source or "runtime"),
        summary=_one_line(summary),
        details=_jsonable(details or {}),
        task_id=task_id,
    )
    with _LOCK:
        _ENTRIES.append(entry)
    _trace(entry)
    _append_audit(_audit_from_evidence(entry))
    return entry


def record_tool_result(
    tool_name: str,
    args: dict,
    *,
    ok: bool,
    output: str,
    task_id: str | None = None,
) -> EvidenceEntry:
    if task_id is None:
        try:
            from . import runtime

            task_id = runtime.current_agent_task_id() or runtime.current_task_id()
        except Exception:
            task_id = None
    kind = _tool_kind(tool_name, args, ok)
    summary = _tool_summary(tool_name, args, ok)
    details = {
        "tool": tool_name,
        "ok": bool(ok),
        "args": _tool_args_for_evidence(tool_name, args),
        "output_head": _clip(str(output or ""), 1000),
    }
    entry = record(kind, tool_name, summary, details=details, task_id=task_id)
    if tool_name in {"bash", "bash_start"} and _CHECK_COMMAND_RE.search(str(args.get("command", ""))):
        record_verification(
            VerificationResult(
                status="PASS" if ok else "FAIL",
                commands=[str(args.get("command", ""))],
                findings=[] if ok else [_clip(str(output or ""), 1000)],
                task_id=task_id,
            ),
            source=tool_name,
        )
    return entry


def record_verification(result: VerificationResult, *, source: str = "verifier") -> EvidenceEntry:
    summary = f"{result.status}"
    if result.commands:
        summary += " " + "; ".join(result.commands[:2])
    return record(
        "verification",
        source,
        summary,
        details=asdict(result),
        task_id=result.task_id,
    )


def entries(*, kind: str | None = None, task_id: str | None = None) -> list[EvidenceEntry]:
    with _LOCK:
        items = list(_ENTRIES)
    if kind is not None:
        items = [entry for entry in items if entry.kind == kind]
    if task_id is not None:
        items = [entry for entry in items if entry.task_id == task_id]
    return items


def snapshot() -> list[dict[str, Any]]:
    return [asdict(entry) for entry in entries()]


def audit_entries(*, task_id: str | None = None, limit: int = 100) -> list[AuditEntry]:
    out: list[AuditEntry] = []
    path = audit_path()
    if not path.exists():
        return out
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines[-max(1, limit):]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if task_id is not None and item.get("task_id") != task_id:
            continue
        try:
            out.append(
                AuditEntry(
                    audit_id=str(item.get("audit_id") or ""),
                    phase=str(item.get("phase") or "did"),
                    source=str(item.get("source") or "runtime"),
                    summary=str(item.get("summary") or ""),
                    details=item.get("details") if isinstance(item.get("details"), dict) else {},
                    task_id=str(item.get("task_id")) if item.get("task_id") is not None else None,
                    created_at=float(item.get("created_at") or 0.0),
                )
            )
        except Exception:
            continue
    return [entry for entry in out if entry.audit_id]


def audit_summary(*, task_id: str | None = None, limit: int = 8) -> str:
    items = audit_entries(task_id=task_id, limit=limit)
    if not items:
        return "(no audit entries recorded)"
    return "\n".join(f"- {item.audit_id} {item.phase}/{item.source}: {item.summary}" for item in items[-limit:])


def latest_verifications() -> list[VerificationResult]:
    out: list[VerificationResult] = []
    for entry in entries(kind="verification"):
        details = entry.details
        try:
            out.append(
                VerificationResult(
                    status=str(details.get("status", "SKIPPED")),
                    commands=[str(item) for item in details.get("commands", [])],
                    findings=[str(item) for item in details.get("findings", [])],
                    risk=str(details.get("risk", "")),
                    task_id=entry.task_id,
                )
            )
        except Exception:
            continue
    return out


def has_passing_verification() -> bool:
    return any(result.status == "PASS" for result in latest_verifications())


def has_any_verification() -> bool:
    return bool(latest_verifications())


def evidence_summary(limit: int = 8) -> str:
    items = entries()[-max(1, limit):]
    if not items:
        return "(no runtime evidence recorded)"
    return "\n".join(f"- {item.id} {item.kind}/{item.source}: {item.summary}" for item in items)


def _audit_from_evidence(entry: EvidenceEntry) -> AuditEntry:
    return AuditEntry(
        audit_id=entry.id.replace("ev_", "audit_", 1),
        phase=_phase_for(entry.kind),
        source=entry.source,
        summary=redact.text(entry.summary),
        details=redact.content(entry.details),
        task_id=entry.task_id,
        created_at=entry.created_at,
    )


def _append_audit(entry: AuditEntry) -> None:
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(entry), ensure_ascii=False, separators=(",", ":")) + "\n")
    settings.restrict_file_permissions(path)


def _phase_for(kind: str) -> str:
    if kind == "inspection":
        return "saw"
    if kind == "policy":
        return "decided"
    if kind == "change":
        return "changed"
    if kind == "verification":
        return "verified"
    if kind in {"agent", "tool_result"}:
        return "did"
    return "needs" if kind == "open_loop" else "did"


def _tool_kind(tool_name: str, args: dict, ok: bool) -> str:
    if tool_name in {"write_file", "edit_file", "multi_edit"}:
        return "change" if ok else "tool_result"
    if tool_name in {"read_file", "grep", "glob", "list_files", "git"}:
        return "inspection"
    if tool_name in {
        "spawn_agent",
        "send_agent_message",
        "agent_output",
        "list_agents",
        "stop_agent",
        "cleanup_agent",
    }:
        return "agent"
    if tool_name in {"bash", "bash_start"} and _CHECK_COMMAND_RE.search(str(args.get("command", ""))):
        return "verification"
    return "tool_result"


def _tool_summary(tool_name: str, args: dict, ok: bool) -> str:
    status = "ok" if ok else "failed"
    if tool_name in {"bash", "bash_start"}:
        return f"{status}: {str(args.get('command', ''))[:160]}"
    if tool_name == "multi_edit":
        changes = args.get("changes") if isinstance(args, dict) else []
        return f"{status}: multi_edit {len(changes) if isinstance(changes, list) else 0} change(s)"
    path = args.get("path") if isinstance(args, dict) else ""
    return f"{status}: {tool_name} {path}".strip()


def _tool_args_for_evidence(tool_name: str, args: dict) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    if tool_name in {"write_file", "edit_file", "multi_edit"}:
        out = dict(args)
        for key in ("content", "old", "new"):
            if key in out and isinstance(out[key], str):
                out[key] = _clip(out[key], 160)
        if isinstance(out.get("edits"), list):
            out["edits"] = f"{len(out['edits'])} edit(s)"
        if isinstance(out.get("changes"), list):
            out["changes"] = f"{len(out['changes'])} change(s)"
        return out
    return dict(args)


def _one_line(text: str, limit: int = 240) -> str:
    text = str(text or "").replace("\n", " | ").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "... [truncated]"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return str(value)


def _trace(entry: EvidenceEntry) -> None:
    try:
        from . import tracing

        tracing.emit(
            "evidence_recorded",
            evidence_id=entry.id,
            kind=entry.kind,
            source=entry.source,
            summary=entry.summary,
            task_id=entry.task_id,
        )
    except Exception:
        return
