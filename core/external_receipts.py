"""Receipt ledger for approval-gated external actions."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import redact, session, settings


SCHEMA_VERSION = 1
EXTERNAL_RE = re.compile(r"\b(post|publish|send|email|dm|message|buy|purchase|pay|account|login|reddit|stripe)\b", re.I)


@dataclass(frozen=True)
class ExternalReceipt:
    receipt_id: str
    cwd: str
    source: str
    action_type: str
    title: str
    target: str = ""
    external_ref: str = ""
    approval_status: str = ""
    before_state: str = ""
    after_state: str = ""
    outcome: str = ""
    rollback_hint: str = ""
    note: str = ""
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def receipts_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "external_receipts" / "receipts.jsonl"


def record_receipt(
    cwd: str | Path,
    *,
    source: str,
    action_type: str,
    title: str,
    target: str = "",
    external_ref: str = "",
    approval_status: str = "",
    before_state: str = "",
    after_state: str = "",
    outcome: str = "",
    rollback_hint: str = "",
    note: str = "",
) -> ExternalReceipt:
    root = Path(cwd).expanduser().resolve()
    receipt = ExternalReceipt(
        receipt_id="receipt_" + uuid.uuid4().hex[:12],
        cwd=str(root),
        source=_clean(source, 80),
        action_type=_clean(action_type, 80),
        title=_clean(title, 180) or "External action",
        target=_clean(target, 300),
        external_ref=_clean(external_ref, 200),
        approval_status=_clean(approval_status, 80),
        before_state=_clean(before_state, 160),
        after_state=_clean(after_state, 160),
        outcome=_clean(outcome, 500),
        rollback_hint=_clean(rollback_hint or _rollback_hint(action_type, target), 500),
        note=_clean(note, 500),
        created_at=int(time.time()),
    )
    path = receipts_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
    settings.restrict_file_permissions(path)
    return receipt


def record_draft_transition(
    cwd: str | Path,
    draft: dict[str, Any],
    *,
    before_status: str,
    after_status: str,
    note: str = "",
) -> ExternalReceipt | None:
    if after_status not in {"approved", "denied", "cancelled"}:
        return None
    return record_receipt(
        cwd,
        source="external-draft",
        action_type=str(draft.get("kind") or "external-action"),
        title=str(draft.get("title") or "External action draft"),
        target=str(draft.get("target") or ""),
        external_ref=str(draft.get("draft_id") or ""),
        approval_status=after_status,
        before_state=before_status,
        after_state=after_status,
        outcome=f"Draft marked {after_status}; no external effect is implied until execution is separately confirmed.",
        rollback_hint="Keep the draft local, cancel it, or revert the external system manually if it was executed elsewhere.",
        note=note,
    )


def record_publication(
    cwd: str | Path,
    post: dict[str, Any],
    *,
    before_status: str,
    url: str,
) -> ExternalReceipt:
    return record_receipt(
        cwd,
        source="public-posting",
        action_type=f"{post.get('platform') or 'public'}-post",
        title=str(post.get("title") or "Public post"),
        target=str(post.get("platform") or ""),
        external_ref=str(post.get("post_id") or ""),
        approval_status="published",
        before_state=before_status,
        after_state="published",
        outcome=f"Publication marked live at {url}.",
        rollback_hint="Open the destination URL, delete/unpublish the post if needed, then log the manual rollback result.",
        note=str(post.get("approval_note") or ""),
    )


def list_receipts(cwd: str | Path, *, limit: int = 80) -> list[ExternalReceipt]:
    path = receipts_path(cwd)
    if not path.exists():
        return []
    rows: list[ExternalReceipt] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in reversed(lines[-500:]):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                ExternalReceipt(
                    receipt_id=str(item.get("receipt_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    source=str(item.get("source") or ""),
                    action_type=str(item.get("action_type") or ""),
                    title=str(item.get("title") or ""),
                    target=str(item.get("target") or ""),
                    external_ref=str(item.get("external_ref") or ""),
                    approval_status=str(item.get("approval_status") or ""),
                    before_state=str(item.get("before_state") or ""),
                    after_state=str(item.get("after_state") or ""),
                    outcome=str(item.get("outcome") or ""),
                    rollback_hint=str(item.get("rollback_hint") or ""),
                    note=str(item.get("note") or ""),
                    created_at=int(item.get("created_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.receipt_id][: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    receipts = list_receipts(cwd, limit=80)
    return {
        "schema": SCHEMA_VERSION,
        "total": len(receipts),
        "approved": sum(1 for row in receipts if row.approval_status in {"approved", "published"}),
        "denied": sum(1 for row in receipts if row.approval_status == "denied"),
        "receipts": [row.to_dict() for row in receipts[:20]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    receipts = list_receipts(cwd, limit=limit)
    if not receipts:
        return ""
    lines = ["# External Action Receipts"]
    for receipt in receipts:
        lines.append(
            f"- {receipt.approval_status} {receipt.action_type}: {receipt.title}; target={receipt.target or 'n/a'}; rollback={receipt.rollback_hint[:160]}"
        )
    return "\n".join(lines)


def looks_external(text: str) -> bool:
    return bool(EXTERNAL_RE.search(str(text or "")))


def _rollback_hint(action_type: str, target: str) -> str:
    haystack = f"{action_type} {target}".lower()
    if any(term in haystack for term in ("pay", "purchase", "stripe")):
        return "Open the payment/provider dashboard and void, refund, cancel, or document the transaction state."
    if any(term in haystack for term in ("post", "reddit", "twitter", "x", "linkedin", "discord")):
        return "Open the destination, delete/unpublish the content if needed, and log the final URL/state."
    if any(term in haystack for term in ("email", "dm", "message", "send")):
        return "Sent messages cannot be recalled reliably; send a correction/follow-up and log the thread."
    return "Capture before/after evidence and record the manual rollback step for the external system."


def _clean(value: str, limit: int) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
