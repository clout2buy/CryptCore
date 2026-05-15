"""Reference-only credential need tracker.

This module intentionally never stores raw secrets. It stores service names,
account hints, and references such as environment variable names or password
manager item labels.
"""
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
NEED_RE = re.compile(r"\b(api key|oauth|login|log in|account|credential|password|token|stripe|gmail|reddit|github)\b", re.I)
STATUSES = {"needed", "available", "blocked", "revoked", "not-needed"}


@dataclass(frozen=True)
class CredentialReference:
    ref_id: str
    cwd: str
    service: str
    purpose: str
    account_hint: str = ""
    reference: str = ""
    status: str = "needed"
    approval_required: bool = True
    notes: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def vault_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "credentials" / "references.json"


def add_reference(
    cwd: str | Path,
    *,
    service: str,
    purpose: str,
    account_hint: str = "",
    reference: str = "",
    status: str = "needed",
    note: str = "",
) -> CredentialReference:
    root = Path(cwd).expanduser().resolve()
    _reject_secret(service, purpose, account_hint, reference, note)
    now = _now()
    service_clean = _clean(service, 120) or "unknown service"
    existing = _existing(root, service_clean, purpose)
    ref = CredentialReference(
        ref_id=existing.ref_id if existing else "cred_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        service=service_clean,
        purpose=_clean(purpose, 500) or "credential needed",
        account_hint=_clean(account_hint, 180),
        reference=_clean(reference, 240),
        status=_status(status),
        approval_required=True,
        notes=_dedupe([note, *(existing.notes if existing else [])]),
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    rows = [row for row in list_references(root, include_all=True) if row.ref_id != ref.ref_id]
    rows.insert(0, ref)
    _write(root, rows)
    return ref


def observe_need(cwd: str | Path, text: str) -> CredentialReference | None:
    clean = _clean(text, 1_000)
    if not clean or not NEED_RE.search(clean):
        return None
    service = _service_from_text(clean)
    purpose = f"Needed for: {clean}"
    return add_reference(cwd, service=service, purpose=purpose, note="observed from chat")


def update_status(cwd: str | Path, ref_id: str, *, status: str, reference: str = "", note: str = "") -> CredentialReference:
    root = Path(cwd).expanduser().resolve()
    _reject_secret(reference, note)
    rows = []
    updated: CredentialReference | None = None
    for row in list_references(root, include_all=True):
        if row.ref_id != ref_id:
            rows.append(row)
            continue
        updated = replace(
            row,
            status=_status(status),
            reference=_clean(reference or row.reference, 240),
            notes=_dedupe([note, *row.notes]),
            updated_at=_now(),
        )
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown credential reference: {ref_id}")
    _write(root, rows)
    return updated


def list_references(cwd: str | Path, *, include_all: bool = False, limit: int = 80) -> list[CredentialReference]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status in {"needed", "available", "blocked"}]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_references(cwd, include_all=True, limit=40)
    return {
        "total": len(rows),
        "needed": sum(1 for row in rows if row.status == "needed"),
        "available": sum(1 for row in rows if row.status == "available"),
        "blocked": sum(1 for row in rows if row.status == "blocked"),
        "references": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_references(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Credential References"]
    for row in rows:
        ref = f"; ref={row.reference}" if row.reference else ""
        lines.append(f"- {row.status} {row.service}: {row.purpose}{ref}; never ask the user to paste raw secrets into chat")
    return "\n".join(lines)


def _read(cwd: str | Path) -> list[CredentialReference]:
    path = vault_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("references", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                CredentialReference(
                    ref_id=str(item.get("ref_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    service=str(item.get("service") or ""),
                    purpose=str(item.get("purpose") or ""),
                    account_hint=str(item.get("account_hint") or ""),
                    reference=str(item.get("reference") or ""),
                    status=_status(str(item.get("status") or "needed")),
                    approval_required=bool(item.get("approval_required", True)),
                    notes=[str(note) for note in item.get("notes", []) if str(note).strip()],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.ref_id and row.cwd]


def _write(cwd: str | Path, rows: list[CredentialReference]) -> None:
    path = vault_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "references": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _existing(cwd: Path, service: str, purpose: str) -> CredentialReference | None:
    service_key = service.lower()
    purpose_key = _clean(purpose, 500).lower()
    return next(
        (row for row in list_references(cwd, include_all=True) if row.service.lower() == service_key and row.purpose.lower() == purpose_key),
        None,
    )


def _reject_secret(*values: str) -> None:
    text = "\n".join(str(value or "") for value in values)
    findings = secret_hygiene.scan_text(text, file="credential-reference")
    if findings:
        kinds = ", ".join(sorted({finding.kind for finding in findings}))
        raise ValueError(f"raw secret-looking value refused: {kinds}")


def _service_from_text(text: str) -> str:
    lower = text.lower()
    for service in ("stripe", "gmail", "reddit", "github", "openai", "anthropic", "google", "discord", "slack"):
        if service in lower:
            return service
    if "api key" in lower:
        return "api key"
    if "oauth" in lower:
        return "oauth"
    return "account"


def _status(value: str) -> str:
    clean = str(value or "needed").strip().lower()
    return clean if clean in STATUSES else "needed"


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value, 500)
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
