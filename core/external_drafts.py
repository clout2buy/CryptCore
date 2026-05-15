"""Approval-first queue for actions that affect external systems."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import evidence, settings


SCHEMA_VERSION = 1
STATUSES = {"draft", "pending-approval", "approved", "denied", "cancelled"}
EXTERNAL_RE = re.compile(
    r"\b(post|publish|tweet|reddit|email|dm|message|send|buy|purchase|pay|create account|sign up|login|log in)\b",
    re.I,
)


@dataclass(frozen=True)
class ExternalDraft:
    draft_id: str
    cwd: str
    kind: str
    title: str
    target: str = ""
    content: str = ""
    source_prompt: str = ""
    status: str = "draft"
    risk: str = "high"
    approval_note: str = ""
    created_at: int = 0
    updated_at: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def drafts_path() -> Path:
    return settings.APP_DIR / "external_actions" / "drafts.json"


def create_draft(
    cwd: str | Path,
    *,
    kind: str,
    title: str,
    target: str = "",
    content: str = "",
    source_prompt: str = "",
    risk: str = "high",
) -> ExternalDraft:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    draft = ExternalDraft(
        draft_id="draft_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        kind=_kind(kind),
        title=_clean(title, 160) or "External action draft",
        target=_clean(target, 300),
        content=_clean(content, 5_000),
        source_prompt=_clean(source_prompt, 2_000),
        status="pending-approval",
        risk=_risk(risk),
        created_at=now,
        updated_at=now,
        history=[_history("created", "draft queued for approval", now)],
    )
    drafts = list_drafts(include_all=True)
    drafts.insert(0, draft)
    _write(drafts)
    evidence.record(
        "external-draft",
        "external_drafts",
        f"Queued {draft.kind} draft: {draft.title}",
        details={"draft_id": draft.draft_id, "risk": draft.risk, "target": draft.target},
    )
    return draft


def draft_from_prompt(cwd: str | Path, text: str) -> ExternalDraft | None:
    clean = _clean(text, 2_000)
    if not clean or not EXTERNAL_RE.search(clean):
        return None
    kind = classify_kind(clean)
    return create_draft(
        cwd,
        kind=kind,
        title=_title_for(kind, clean),
        target=_target_hint(clean),
        content=(
            "Draft requested from chat. Crypt may prepare exact copy, assets, or steps, "
            "but this item must be approved before any external effect happens."
        ),
        source_prompt=clean,
        risk="critical" if kind in {"purchase", "account", "payment"} else "high",
    )


def list_drafts(cwd: str | Path | None = None, *, include_all: bool = False, limit: int = 100) -> list[ExternalDraft]:
    root = str(Path(cwd).expanduser().resolve()) if cwd else ""
    drafts = _read()
    if root:
        drafts = [draft for draft in drafts if draft.cwd == root]
    if not include_all:
        drafts = [draft for draft in drafts if draft.status in {"draft", "pending-approval", "approved"}]
    drafts.sort(key=lambda draft: draft.updated_at, reverse=True)
    return drafts[: max(1, limit)]


def update_status(draft_id: str, status: str, *, note: str = "") -> ExternalDraft:
    clean_status = str(status or "").strip().lower()
    if clean_status not in STATUSES:
        raise ValueError(f"unknown external draft status: {status}")
    drafts = list_drafts(include_all=True, limit=10_000)
    now = _now()
    out: list[ExternalDraft] = []
    updated: ExternalDraft | None = None
    for draft in drafts:
        if draft.draft_id != draft_id:
            out.append(draft)
            continue
        data = draft.to_dict()
        data["status"] = clean_status
        data["approval_note"] = _clean(note, 1_000)
        data["updated_at"] = now
        data["history"] = [*draft.history, _history(clean_status, note or f"status set to {clean_status}", now)]
        updated = ExternalDraft(**data)
        out.append(updated)
    if updated is None:
        raise KeyError(f"unknown external draft: {draft_id}")
    _write(out)
    evidence.record(
        "external-draft",
        "external_drafts",
        f"External draft {draft_id} marked {clean_status}",
        details={"draft_id": draft_id, "status": clean_status, "note": note},
    )
    return updated


def snapshot(cwd: str | Path) -> dict[str, Any]:
    drafts = list_drafts(cwd, include_all=True, limit=50)
    pending = [draft for draft in drafts if draft.status == "pending-approval"]
    return {
        "total": len(drafts),
        "pending": len(pending),
        "approved": sum(1 for draft in drafts if draft.status == "approved"),
        "drafts": [draft.to_dict() for draft in drafts[:20]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    drafts = list_drafts(cwd, limit=limit)
    if not drafts:
        return ""
    lines = ["# External Draft Queue"]
    for draft in drafts:
        lines.append(
            f"- {draft.status} {draft.kind}: {draft.title}; target={draft.target or 'unspecified'}; approval required before external effect"
        )
    return "\n".join(lines)


def classify_kind(text: str) -> str:
    lower = str(text or "").lower()
    if "reddit" in lower:
        return "reddit-post"
    if "email" in lower:
        return "email"
    if "dm" in lower or "message" in lower:
        return "message"
    if any(term in lower for term in ("buy", "purchase")):
        return "purchase"
    if "pay" in lower or "payment" in lower:
        return "payment"
    if "create account" in lower or "sign up" in lower or "login" in lower or "log in" in lower:
        return "account"
    if "post" in lower or "publish" in lower or "tweet" in lower:
        return "public-post"
    return "external-action"


def _read() -> list[ExternalDraft]:
    path = drafts_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[ExternalDraft] = []
    for item in data.get("drafts", []):
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                ExternalDraft(
                    draft_id=str(item.get("draft_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    kind=_kind(str(item.get("kind") or "external-action")),
                    title=_clean(str(item.get("title") or ""), 160),
                    target=_clean(str(item.get("target") or ""), 300),
                    content=_clean(str(item.get("content") or ""), 5_000),
                    source_prompt=_clean(str(item.get("source_prompt") or ""), 2_000),
                    status=str(item.get("status") or "draft") if str(item.get("status") or "draft") in STATUSES else "draft",
                    risk=_risk(str(item.get("risk") or "high")),
                    approval_note=_clean(str(item.get("approval_note") or ""), 1_000),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                    history=item.get("history") if isinstance(item.get("history"), list) else [],
                )
            )
        except Exception:
            continue
    return [draft for draft in out if draft.draft_id and draft.cwd]


def _write(drafts: list[ExternalDraft]) -> None:
    path = drafts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "drafts": [draft.to_dict() for draft in drafts]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _history(action: str, note: str, ts: int) -> dict[str, Any]:
    return {"action": _clean(action, 80), "note": _clean(note, 500), "at": ts}


def _title_for(kind: str, text: str) -> str:
    prefix = {
        "reddit-post": "Review Reddit post",
        "email": "Review email",
        "message": "Review message",
        "purchase": "Review purchase",
        "payment": "Review payment",
        "account": "Review account action",
        "public-post": "Review public post",
    }.get(kind, "Review external action")
    return f"{prefix}: {_clean(text, 70)}"


def _target_hint(text: str) -> str:
    lower = str(text or "").lower()
    for marker in ("reddit", "email", "twitter", "x.com", "discord", "slack", "stripe"):
        if marker in lower:
            return marker
    return ""


def _kind(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(value or "external-action").strip().lower()).strip("-") or "external-action"


def _risk(value: str) -> str:
    clean = str(value or "high").strip().lower()
    return clean if clean in {"low", "medium", "high", "critical"} else "high"


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
