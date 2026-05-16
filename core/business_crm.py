"""Lightweight local CRM for leads, customers, opportunities, and follow-ups."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import redact, session, settings


SCHEMA_VERSION = 1
CONTACT_STATUSES = {"lead", "prospect", "customer", "partner", "archived"}
OPPORTUNITY_STAGES = {"idea", "contacted", "qualified", "proposal", "won", "lost"}
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
NAME_RE = re.compile(r"\b(?:lead|customer|client|prospect)\s+(?:called|named|is)?\s*(?P<name>[A-Za-z][A-Za-z0-9 &'_.-]{1,80})", re.I)
MONEY_RE = re.compile(r"\$(?P<amount>[0-9]+(?:\.[0-9]{1,2})?)")


@dataclass(frozen=True)
class CRMContact:
    contact_id: str
    name: str
    status: str = "lead"
    email: str = ""
    company: str = ""
    source: str = "chat"
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    next_action: str = ""
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CRMOpportunity:
    opportunity_id: str
    contact_id: str
    title: str
    stage: str = "idea"
    value_usd: float = 0.0
    probability: float = 0.25
    next_action: str = ""
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CRMInteraction:
    interaction_id: str
    contact_id: str
    channel: str
    summary: str
    next_action: str = ""
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CRMObservation:
    changed: bool
    contacts: list[CRMContact] = field(default_factory=list)
    opportunities: list[CRMOpportunity] = field(default_factory=list)


def crm_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "business" / "crm.json"


def upsert_contact(
    cwd: str | Path,
    *,
    name: str,
    email: str = "",
    company: str = "",
    status: str = "lead",
    source: str = "chat",
    tags: list[str] | None = None,
    note: str = "",
    next_action: str = "",
) -> CRMContact:
    now = _now()
    clean_email = _clean(email, 160).lower()
    clean_name = _clean(name, 120) or (clean_email.split("@")[0] if clean_email else "")
    if not clean_name:
        raise ValueError("contact name or email is required")
    state = _read(cwd)
    contact_id = _contact_id(clean_email or clean_name)
    contacts = []
    updated: CRMContact | None = None
    for contact in state["contacts"]:
        if contact.contact_id != contact_id:
            contacts.append(contact)
            continue
        merged = CRMContact(
            contact_id=contact.contact_id,
            name=clean_name or contact.name,
            status=_status(status or contact.status),
            email=clean_email or contact.email,
            company=_clean(company or contact.company, 120),
            source=_clean(source or contact.source, 60),
            tags=_dedupe([*contact.tags, *(tags or []), "crm"]),
            notes=_dedupe([*contact.notes, _clean(note, 500)]),
            next_action=_clean(next_action or contact.next_action, 300),
            created_at=contact.created_at,
            updated_at=now,
        )
        contacts.append(merged)
        updated = merged
    if updated is None:
        updated = CRMContact(
            contact_id=contact_id,
            name=clean_name,
            status=_status(status),
            email=clean_email,
            company=_clean(company, 120),
            source=_clean(source, 60),
            tags=_dedupe([*(tags or []), "crm"]),
            notes=[_clean(note, 500)] if note else [],
            next_action=_clean(next_action, 300),
            created_at=now,
            updated_at=now,
        )
        contacts.insert(0, updated)
    state["contacts"] = contacts[:500]
    _write(cwd, state)
    return updated


def add_opportunity(
    cwd: str | Path,
    *,
    contact_id: str,
    title: str,
    value_usd: float = 0.0,
    stage: str = "idea",
    probability: float = 0.25,
    next_action: str = "",
) -> CRMOpportunity:
    state = _read(cwd)
    now = _now()
    opportunity = CRMOpportunity(
        opportunity_id="opp_" + uuid.uuid4().hex[:10],
        contact_id=_clean(contact_id, 80),
        title=_clean(title, 160) or "Opportunity",
        stage=_stage(stage),
        value_usd=round(max(0.0, float(value_usd or 0.0)), 2),
        probability=max(0.0, min(1.0, float(probability or 0.0))),
        next_action=_clean(next_action, 300),
        created_at=now,
        updated_at=now,
    )
    state["opportunities"].insert(0, opportunity)
    _write(cwd, state)
    return opportunity


def log_interaction(
    cwd: str | Path,
    *,
    contact_id: str,
    channel: str,
    summary: str,
    next_action: str = "",
) -> CRMInteraction:
    state = _read(cwd)
    interaction = CRMInteraction(
        interaction_id="crm_int_" + uuid.uuid4().hex[:10],
        contact_id=_clean(contact_id, 80),
        channel=_clean(channel, 60) or "note",
        summary=_clean(summary, 700),
        next_action=_clean(next_action, 300),
        created_at=_now(),
    )
    state["interactions"].insert(0, interaction)
    _write(cwd, state)
    return interaction


def observe_text(cwd: str | Path, text: str) -> CRMObservation:
    clean = _clean(text, 2_000)
    if not clean or not _looks_crm(clean):
        return CRMObservation(False)
    contacts = []
    opportunities = []
    emails = EMAIL_RE.findall(clean)
    names = [match.group("name").strip(" .") for match in NAME_RE.finditer(clean)]
    if not emails and not names:
        return CRMObservation(False)
    for index, email in enumerate(emails or [""]):
        name = names[index] if index < len(names) else (email.split("@")[0] if email else names[0])
        contact = upsert_contact(
            cwd,
            name=name,
            email=email,
            status="customer" if "customer" in clean.lower() or "client" in clean.lower() else "lead",
            source="chat",
            note=clean,
            next_action=_next_action(clean),
        )
        contacts.append(contact)
        money = MONEY_RE.search(clean)
        if money or any(term in clean.lower() for term in ("deal", "opportunity", "proposal")):
            opportunities.append(
                add_opportunity(
                    cwd,
                    contact_id=contact.contact_id,
                    title=f"{contact.name} opportunity",
                    value_usd=float(money.group("amount")) if money else 0.0,
                    stage="qualified" if "qualified" in clean.lower() else "idea",
                    next_action=_next_action(clean),
                )
            )
    return CRMObservation(bool(contacts or opportunities), contacts=contacts, opportunities=opportunities)


def snapshot(cwd: str | Path) -> dict[str, Any]:
    state = _read(cwd)
    contacts = state["contacts"]
    opportunities = state["opportunities"]
    interactions = state["interactions"]
    open_opps = [opp for opp in opportunities if opp.stage not in {"won", "lost"}]
    return {
        "path": str(crm_path(cwd)),
        "contacts": len(contacts),
        "leads": sum(1 for contact in contacts if contact.status in {"lead", "prospect"}),
        "customers": sum(1 for contact in contacts if contact.status == "customer"),
        "opportunities": len(open_opps),
        "pipelineValueUsd": round(sum(opp.value_usd for opp in open_opps), 2),
        "weightedPipelineUsd": round(sum(opp.value_usd * opp.probability for opp in open_opps), 2),
        "followUps": sum(1 for contact in contacts if contact.next_action),
        "contactPreview": [contact.to_dict() for contact in contacts[:12]],
        "opportunityPreview": [opp.to_dict() for opp in opportunities[:12]],
        "interactionPreview": [item.to_dict() for item in interactions[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 6) -> str:
    data = snapshot(cwd)
    if not data["contacts"] and not data["opportunities"]:
        return ""
    lines = [
        "# Local Business CRM",
        f"- contacts={data['contacts']}; leads={data['leads']}; customers={data['customers']}; pipeline=${data['pipelineValueUsd']:.2f}; followups={data['followUps']}",
    ]
    for contact in data["contactPreview"][:limit]:
        lines.append(f"- {contact['status']} {contact['name']}; email={contact.get('email') or 'n/a'}; next={contact.get('next_action') or 'none'}")
    return "\n".join(lines)


def _read(cwd: str | Path) -> dict[str, list[Any]]:
    path = crm_path(cwd)
    if not path.exists():
        return {"contacts": [], "opportunities": [], "interactions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {"contacts": [], "opportunities": [], "interactions": []}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return {"contacts": [], "opportunities": [], "interactions": []}
    return {
        "contacts": [_contact(item) for item in data.get("contacts", []) if isinstance(item, dict)],
        "opportunities": [_opportunity(item) for item in data.get("opportunities", []) if isinstance(item, dict)],
        "interactions": [_interaction(item) for item in data.get("interactions", []) if isinstance(item, dict)],
    }


def _write(cwd: str | Path, state: dict[str, list[Any]]) -> None:
    path = crm_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": SCHEMA_VERSION,
                "contacts": [item.to_dict() for item in state.get("contacts", [])],
                "opportunities": [item.to_dict() for item in state.get("opportunities", [])],
                "interactions": [item.to_dict() for item in state.get("interactions", [])],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _contact(item: dict[str, Any]) -> CRMContact:
    return CRMContact(
        contact_id=str(item.get("contact_id") or ""),
        name=str(item.get("name") or ""),
        status=_status(str(item.get("status") or "lead")),
        email=str(item.get("email") or ""),
        company=str(item.get("company") or ""),
        source=str(item.get("source") or "chat"),
        tags=[str(value) for value in item.get("tags", []) if str(value).strip()],
        notes=[str(value) for value in item.get("notes", []) if str(value).strip()],
        next_action=str(item.get("next_action") or ""),
        created_at=int(item.get("created_at") or 0),
        updated_at=int(item.get("updated_at") or 0),
    )


def _opportunity(item: dict[str, Any]) -> CRMOpportunity:
    return CRMOpportunity(
        opportunity_id=str(item.get("opportunity_id") or ""),
        contact_id=str(item.get("contact_id") or ""),
        title=str(item.get("title") or ""),
        stage=_stage(str(item.get("stage") or "idea")),
        value_usd=float(item.get("value_usd") or 0.0),
        probability=float(item.get("probability") or 0.0),
        next_action=str(item.get("next_action") or ""),
        created_at=int(item.get("created_at") or 0),
        updated_at=int(item.get("updated_at") or 0),
    )


def _interaction(item: dict[str, Any]) -> CRMInteraction:
    return CRMInteraction(
        interaction_id=str(item.get("interaction_id") or ""),
        contact_id=str(item.get("contact_id") or ""),
        channel=str(item.get("channel") or ""),
        summary=str(item.get("summary") or ""),
        next_action=str(item.get("next_action") or ""),
        created_at=int(item.get("created_at") or 0),
    )


def _looks_crm(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in ("lead", "customer", "client", "prospect", "crm", "opportunity", "deal", "proposal")) and (
        EMAIL_RE.search(text) or NAME_RE.search(text)
    )


def _next_action(text: str) -> str:
    lower = text.lower()
    if "follow up" in lower:
        return "Follow up with this contact."
    if "proposal" in lower:
        return "Prepare or review the proposal."
    if "email" in lower:
        return "Draft a local email and hold for approval before sending."
    return "Review this CRM record and choose the next useful step."


def _contact_id(value: str) -> str:
    digest = hashlib.sha1(value.lower().encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"contact_{digest}"


def _status(value: str) -> str:
    clean = str(value or "lead").strip().lower()
    return clean if clean in CONTACT_STATUSES else "lead"


def _stage(value: str) -> str:
    clean = str(value or "idea").strip().lower()
    return clean if clean in OPPORTUNITY_STAGES else "idea"


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
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
