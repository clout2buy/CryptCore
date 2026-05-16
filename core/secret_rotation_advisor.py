"""Sanitized secret rotation checklist advisor.

The advisor detects secret-looking values in chat/tool/runtime text, but it
never stores the raw value. Persistent records contain a stable fingerprint,
redacted excerpts, and rotation steps.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from . import redact, session, settings


SCHEMA_VERSION = 1
MAX_SIGNALS = 250

PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"), "critical"),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "critical"),
    ("github-token", re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}\b"), "critical"),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"), "critical"),
    ("discord-token", re.compile(r"\b[MN][A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,}\b"), "critical"),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "critical"),
    (
        "secret-assignment",
        re.compile(
            r"(?i)\b(?:[A-Z0-9_.-]*"
            r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API[_-]?KEY|APIKEY|AUTH(?:ORIZATION)?|"
            r"CREDENTIAL|WEBHOOK|PRIVATE[_-]?KEY)"
            r"[A-Z0-9_.-]*)\s*[:=]\s*[^\s\"']+"
        ),
        "high",
    ),
)


@dataclass(frozen=True)
class SecretSignal:
    signal_id: str
    kind: str
    source: str
    fingerprint: str
    redacted_excerpt: str
    severity: str = "high"
    checklist: list[str] = field(default_factory=list)
    seen_count: int = 1
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def advice_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "security" / "secret_rotation_advice.json"


def inspect_text(cwd: str | Path, text: str, *, source: str = "runtime") -> list[SecretSignal]:
    """Detect secret-looking text and persist sanitized rotation advice."""
    value = str(text or "")
    if not value:
        return []
    root = Path(cwd).expanduser().resolve()
    now = _now()
    existing = {row.signal_id: row for row in list_signals(root, limit=MAX_SIGNALS)}
    changed: list[SecretSignal] = []
    for finding in _find(value, source=source):
        previous = existing.get(finding.signal_id)
        if previous:
            finding = replace(
                previous,
                source=_merge_source(previous.source, finding.source),
                redacted_excerpt=finding.redacted_excerpt or previous.redacted_excerpt,
                seen_count=previous.seen_count + 1,
                updated_at=now,
            )
        else:
            finding = replace(finding, created_at=now, updated_at=now)
        existing[finding.signal_id] = finding
        changed.append(finding)
    if changed:
        rows = sorted(existing.values(), key=lambda row: row.updated_at, reverse=True)[:MAX_SIGNALS]
        _write(root, rows)
    return changed


def scan_event(cwd: str | Path, event: dict[str, Any]) -> list[SecretSignal]:
    if not isinstance(event, dict):
        return []
    parts: list[str] = []
    for key in ("text", "error", "prompt", "command", "output", "result"):
        value = event.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("args", "data", "message"):
        value = event.get(key)
        if isinstance(value, (dict, list)):
            parts.append(json.dumps(value, ensure_ascii=False, default=str))
        elif isinstance(value, str):
            parts.append(value)
    if not parts:
        return []
    source = f"event:{_clean(str(event.get('event') or 'runtime'), 80)}"
    return inspect_text(cwd, "\n".join(parts), source=source)


def list_signals(cwd: str | Path, *, limit: int = 80) -> list[SecretSignal]:
    rows = _read(cwd)
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_signals(cwd, limit=80)
    return {
        "schema": SCHEMA_VERSION,
        "total": len(rows),
        "critical": sum(1 for row in rows if row.severity == "critical"),
        "high": sum(1 for row in rows if row.severity == "high"),
        "byKind": _counts(row.kind for row in rows),
        "signals": [row.to_dict() for row in rows[:20]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_signals(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Secret Rotation Advisor"]
    for row in rows:
        steps = "; ".join(row.checklist[:3])
        lines.append(
            f"- {row.severity} {row.kind} from {row.source}: fingerprint {row.fingerprint}; "
            f"{steps}; never echo or persist the raw secret"
        )
    return "\n".join(lines)


def checklist_for(kind: str) -> list[str]:
    service = _service(kind)
    return [
        f"Identify the owning {service} account, app, and environment where this credential is used.",
        f"Revoke or rotate the exposed {service} credential in the provider console.",
        "Update the replacement value only in the approved environment variable, secret manager, or password manager reference.",
        "Restart or redeploy dependent services so the old value stops being accepted.",
        "Audit provider logs and recent account activity for suspicious use around the exposure time.",
        "Remove the leaked value from files, chat logs, artifacts, and git history where policy allows.",
    ]


def _find(text: str, *, source: str) -> list[SecretSignal]:
    out: list[SecretSignal] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern, severity in PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(0)
            fingerprint = _fingerprint(kind, raw)
            key = (kind, fingerprint)
            if key in seen:
                continue
            seen.add(key)
            excerpt = _excerpt(text, match.start(), match.end())
            out.append(
                SecretSignal(
                    signal_id=f"secret_{fingerprint}",
                    kind=kind,
                    source=_clean(source, 140) or "runtime",
                    fingerprint=fingerprint,
                    redacted_excerpt=_redacted_excerpt(excerpt, kind=kind),
                    severity=severity,
                    checklist=checklist_for(kind),
                )
            )
    return out


def _read(cwd: str | Path) -> list[SecretSignal]:
    path = advice_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("signals", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                SecretSignal(
                    signal_id=str(item.get("signal_id") or ""),
                    kind=str(item.get("kind") or "secret-assignment"),
                    source=str(item.get("source") or "runtime"),
                    fingerprint=str(item.get("fingerprint") or ""),
                    redacted_excerpt=redact.text(str(item.get("redacted_excerpt") or "")),
                    severity=str(item.get("severity") or "high"),
                    checklist=[_clean(str(step), 260) for step in item.get("checklist", []) if str(step).strip()],
                    seen_count=max(1, int(item.get("seen_count") or 1)),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.signal_id and row.fingerprint]


def _write(cwd: str | Path, rows: list[SecretSignal]) -> None:
    path = advice_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "signals": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _redacted_excerpt(value: str, *, kind: str) -> str:
    clean = redact.text(value)
    if kind == "private-key":
        clean = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "[redacted-private-key]", clean)
    return _clean(clean, 260)


def _excerpt(text: str, start: int, end: int) -> str:
    left = max(0, start - 70)
    right = min(len(text), end + 70)
    return text[left:right]


def _fingerprint(kind: str, raw: str) -> str:
    digest = hashlib.sha256(f"{kind}:{raw}".encode("utf-8", errors="replace")).hexdigest()
    return digest[:16]


def _service(kind: str) -> str:
    if kind == "openai-key":
        return "OpenAI"
    if kind == "anthropic-key":
        return "Anthropic"
    if kind == "github-token":
        return "GitHub"
    if kind == "slack-token":
        return "Slack"
    if kind == "discord-token":
        return "Discord"
    if kind == "private-key":
        return "private key"
    return "secret"


def _merge_source(left: str, right: str) -> str:
    values = []
    for value in (left, right):
        for part in str(value or "").split(","):
            clean = _clean(part, 80)
            if clean and clean not in values:
                values.append(clean)
    return ", ".join(values[:4])


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _clean(value: str, limit: int) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
