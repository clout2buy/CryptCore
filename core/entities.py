"""Typed contact, account, and relationship memory for Crypt."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import redact, secret_hygiene, session, settings


SCHEMA_VERSION = 1
MAX_ENTITIES = 500
MAX_EXCERPT_CHARS = 420
VALID_KINDS = {"person", "brand", "business", "account", "channel", "relationship"}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
REDDIT_SUB_RE = re.compile(r"(?<![\w/])r/([A-Za-z0-9_][A-Za-z0-9_]{1,20})\b")
REDDIT_USER_RE = re.compile(r"(?<![\w/])u/([A-Za-z0-9_][A-Za-z0-9_]{1,20})\b")
HANDLE_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9_][A-Za-z0-9_.-]{1,30})\b")
URL_RE = re.compile(r"\bhttps?://([A-Za-z0-9.-]+\.[A-Za-z]{2,})(/[^\s]*)?", re.I)
NAMED_RE = re.compile(
    r"\b(?P<label>brand|business|company|store|startup|project|website|site|"
    r"channel|server|account|profile|person|client|customer|friend|partner|contact)"
    r"\s+(?:called|named|as|is)\s+(?P<name>[A-Za-z0-9][A-Za-z0-9 &'_.-]{1,80})",
    re.I,
)
CHANNEL_RE = re.compile(
    r"\b(?P<platform>youtube|discord|slack|reddit|instagram|tiktok|twitter|x|email)"
    r"\s+(?:channel|server|workspace|account|profile|subreddit|list)"
    r"(?:\s+(?:called|named|is))?\s+(?P<name>[A-Za-z0-9][A-Za-z0-9 &'_.-]{1,70})",
    re.I,
)
MY_PERSON_RE = re.compile(
    r"\bmy\s+(?P<role>friend|client|customer|partner|contact)\s+"
    r"(?P<name>[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){0,2})\b"
)
RELATION_RE = re.compile(
    r"\b(?P<name>[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){0,2})\s+"
    r"is\s+my\s+(?P<role>friend|client|customer|partner|contact)\b",
    re.I,
)


@dataclass(frozen=True)
class EntityRecord:
    entity_id: str
    kind: str
    name: str
    aliases: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    source: str = "webui"
    workspace: str = ""
    confidence: float = 0.65
    sensitivity: str = "normal"
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    mentions: int = 1
    created_at: int = 0
    updated_at: int = 0


@dataclass(frozen=True)
class EntityObservation:
    changed: bool
    path: Path
    records: list[EntityRecord] = field(default_factory=list)
    count: int = 0


def state_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "entities" / "entities.json"


def markdown_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "entities" / "ENTITY_MEMORY.md"


def observe_text(cwd: str | Path, text: str, *, source: str = "webui") -> EntityObservation:
    """Extract typed entities from normal user text and save useful ones."""
    root = Path(cwd).expanduser().resolve()
    path = ensure_store(root)
    clean = _clean_excerpt(text)
    if not clean:
        return EntityObservation(False, path, count=len(list_entities(root)))

    candidates = _extract_candidates(clean)
    if not candidates:
        return EntityObservation(False, path, count=len(list_entities(root)))

    records: list[EntityRecord] = []
    changed = False
    for candidate in candidates:
        record, did_change = upsert_entity(
            root,
            candidate["kind"],
            candidate["name"],
            aliases=candidate.get("aliases"),
            details=candidate.get("details"),
            source=source,
            confidence=float(candidate.get("confidence") or 0.65),
            tags=candidate.get("tags"),
            links=candidate.get("links"),
            sensitivity=candidate.get("sensitivity") or _sensitivity(candidate),
        )
        records.append(record)
        changed = changed or did_change

    return EntityObservation(changed, path, records=records, count=len(list_entities(root)))


def upsert_entity(
    cwd: str | Path,
    kind: str,
    name: str,
    *,
    aliases: list[str] | None = None,
    details: dict[str, Any] | None = None,
    source: str = "webui",
    confidence: float = 0.65,
    sensitivity: str = "normal",
    tags: list[str] | None = None,
    links: list[str] | None = None,
) -> tuple[EntityRecord, bool]:
    clean_kind = _kind(kind)
    clean_name = _clean_name(name)
    if not clean_name:
        raise ValueError("entity name cannot be empty")
    root = Path(cwd).expanduser().resolve()
    ensure_store(root)
    state = _read_state(root)
    now = _now()
    entity_id = _entity_id(clean_kind, clean_name)
    incoming = EntityRecord(
        entity_id=entity_id,
        kind=clean_kind,
        name=clean_name,
        aliases=_dedupe([*(aliases or []), clean_name]),
        details=_safe_details(details or {}),
        source=_clean_token(source or "webui", 40),
        workspace=str(root),
        confidence=max(0.0, min(1.0, float(confidence))),
        sensitivity=sensitivity if sensitivity in {"normal", "private"} else "normal",
        tags=_dedupe([clean_kind, *(tags or [])]),
        links=_dedupe(links or []),
        created_at=now,
        updated_at=now,
    )

    out: list[dict[str, Any]] = []
    changed = False
    merged_record = incoming
    found = False
    for item in state.get("entities", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("entity_id") or "") == entity_id:
            found = True
            merged = _merge(item, incoming)
            changed = changed or merged != item
            merged_record = _record_from_dict(merged)
            out.append(merged)
        else:
            out.append(item)
    if not found:
        out.insert(0, asdict(incoming))
        changed = True

    if changed:
        state["schema"] = SCHEMA_VERSION
        state["workspace"] = str(root)
        state["updated_at"] = now
        state["entities"] = sorted(out, key=lambda row: int(row.get("updated_at") or 0), reverse=True)[:MAX_ENTITIES]
        _write_state(root, state)
        _write_markdown(root, state)
    return merged_record, changed


def list_entities(
    cwd: str | Path,
    *,
    kind: str = "",
    query: str = "",
    limit: int = 100,
    include_private: bool = True,
) -> list[EntityRecord]:
    ensure_store(cwd)
    state = _read_state(cwd)
    requested_kind = _kind(kind) if kind else ""
    needle = _norm(query)
    records: list[EntityRecord] = []
    for item in state.get("entities", []):
        if not isinstance(item, dict):
            continue
        record = _record_from_dict(item)
        if requested_kind and record.kind != requested_kind:
            continue
        if not include_private and record.sensitivity != "normal":
            continue
        haystack = _norm(" ".join([record.name, *record.aliases, *record.tags, json.dumps(record.details, sort_keys=True)]))
        if needle and needle not in haystack:
            continue
        records.append(record)
    records.sort(key=lambda record: (record.mentions, record.updated_at, record.confidence), reverse=True)
    return records[: max(1, limit)]


def snapshot(cwd: str | Path, *, preview: int = 12) -> dict[str, Any]:
    records = list_entities(cwd, limit=max(preview, 1))
    counts: dict[str, int] = {}
    for record in list_entities(cwd, limit=MAX_ENTITIES):
        counts[record.kind] = counts.get(record.kind, 0) + 1
    return {
        "path": str(state_path(cwd)),
        "markdownPath": str(markdown_path(cwd)),
        "count": sum(counts.values()),
        "kindCounts": counts,
        "preview": [asdict(record) for record in records],
    }


def prompt_section(cwd: str | Path, *, limit: int = 12) -> str:
    records = list_entities(cwd, limit=limit, include_private=False)
    if not records:
        return ""
    lines = ["# Contact And Account Memory"]
    for record in records:
        detail = _compact_details(record.details)
        alias_text = f"; aliases: {', '.join(record.aliases[:3])}" if record.aliases and record.aliases != [record.name] else ""
        lines.append(f"- [{record.kind}] {record.name}{alias_text}{detail}")
    return "\n".join(lines)


def ensure_store(cwd: str | Path) -> Path:
    root = Path(cwd).expanduser().resolve()
    path = state_path(root)
    if not path.exists():
        state = _empty_state(root)
        _write_state(root, state)
        _write_markdown(root, state)
    return path


def _extract_candidates(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    excerpt = _clean_excerpt(text)
    for email in EMAIL_RE.findall(text):
        candidates.append(
            {
                "kind": "account",
                "name": email,
                "details": {"platform": "email", "excerpt": excerpt},
                "tags": ["email", "contact"],
                "confidence": 0.92,
                "sensitivity": "private",
            }
        )
    for sub in REDDIT_SUB_RE.findall(text):
        candidates.append(
            {
                "kind": "channel",
                "name": f"r/{sub}",
                "details": {"platform": "reddit", "type": "subreddit", "excerpt": excerpt},
                "tags": ["reddit", "subreddit"],
                "confidence": 0.9,
            }
        )
    for user in REDDIT_USER_RE.findall(text):
        candidates.append(
            {
                "kind": "account",
                "name": f"u/{user}",
                "details": {"platform": "reddit", "type": "user", "excerpt": excerpt},
                "tags": ["reddit", "account"],
                "confidence": 0.86,
            }
        )
    for handle in HANDLE_RE.findall(text):
        candidates.append(
            {
                "kind": "account",
                "name": f"@{handle}",
                "details": {"platform": "social", "excerpt": excerpt},
                "tags": ["handle", "account"],
                "confidence": 0.78,
            }
        )
    for domain, path in URL_RE.findall(text):
        candidates.append(
            {
                "kind": "brand",
                "name": domain.lower(),
                "details": {"platform": "web", "url": f"https://{domain}{path}", "excerpt": excerpt},
                "tags": ["website"],
                "links": [f"https://{domain}{path}"],
                "confidence": 0.74,
            }
        )
    for match in NAMED_RE.finditer(text):
        label = match.group("label").lower()
        name = _clean_name(match.group("name"))
        if not name:
            continue
        kind = _kind_from_label(label)
        details = {"label": label, "excerpt": excerpt}
        candidates.append({"kind": kind, "name": name, "details": details, "tags": [label], "confidence": 0.82})
        if label in {"client", "customer", "friend", "partner", "contact"}:
            candidates.append(_relationship_candidate(name, label, excerpt))
    for match in CHANNEL_RE.finditer(text):
        platform = match.group("platform").lower()
        name = _clean_name(match.group("name"))
        if not name:
            continue
        candidates.append(
            {
                "kind": "channel",
                "name": name,
                "details": {"platform": platform, "excerpt": excerpt},
                "tags": [platform, "channel"],
                "confidence": 0.78,
            }
        )
    for match in MY_PERSON_RE.finditer(text):
        name = _clean_name(match.group("name"))
        role = match.group("role").lower()
        if not name:
            continue
        candidates.append({"kind": "person", "name": name, "details": {"role": role, "excerpt": excerpt}, "tags": [role], "confidence": 0.8})
        candidates.append(_relationship_candidate(name, role, excerpt))
    for match in RELATION_RE.finditer(text):
        name = _clean_name(match.group("name"))
        role = match.group("role").lower()
        if not name:
            continue
        candidates.append({"kind": "person", "name": name, "details": {"role": role, "excerpt": excerpt}, "tags": [role], "confidence": 0.78})
        candidates.append(_relationship_candidate(name, role, excerpt))
    return _dedupe_candidates(candidates)


def _relationship_candidate(name: str, role: str, excerpt: str) -> dict[str, Any]:
    return {
        "kind": "relationship",
        "name": f"{name} -> user:{role}",
        "aliases": [name, role],
        "details": {"subject": name, "target": "user", "relationship": role, "excerpt": excerpt},
        "tags": [role, "relationship"],
        "confidence": 0.76,
    }


def _read_state(cwd: str | Path) -> dict[str, Any]:
    path = state_path(cwd)
    if not path.exists():
        return _empty_state(cwd)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state(cwd)
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return _empty_state(cwd)
    data.setdefault("entities", [])
    return data


def _write_state(cwd: str | Path, state: dict[str, Any]) -> None:
    path = state_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    settings.restrict_file_permissions(path)


def _write_markdown(cwd: str | Path, state: dict[str, Any]) -> None:
    path = markdown_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Entity Memory",
        "",
        "_Local typed memory for people, businesses, accounts, channels, and relationships._",
        "",
        f"- Updated: {_format_time(int(state.get('updated_at') or _now()))}",
        f"- Workspace: {state.get('workspace') or Path(cwd).expanduser().resolve()}",
        "",
    ]
    records = [_record_from_dict(item) for item in state.get("entities", []) if isinstance(item, dict)]
    for kind in sorted(VALID_KINDS):
        group = [record for record in records if record.kind == kind]
        if not group:
            continue
        lines.extend([f"## {kind.title()}s", ""])
        for record in group[:80]:
            details = _compact_details(record.details)
            lines.append(f"- **{record.name}** ({record.mentions} mention(s)){details}")
        lines.append("")
    if not records:
        lines.append("- No entities tracked yet.")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)
    settings.restrict_file_permissions(path)


def _empty_state(cwd: str | Path) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "workspace": str(Path(cwd).expanduser().resolve()),
        "updated_at": _now(),
        "entities": [],
    }


def _merge(existing: dict[str, Any], incoming: EntityRecord) -> dict[str, Any]:
    now = incoming.updated_at
    details = existing.get("details") if isinstance(existing.get("details"), dict) else {}
    details = {**details, **incoming.details}
    return {
        **existing,
        "aliases": _dedupe([*(existing.get("aliases") or []), *incoming.aliases]),
        "details": _safe_details(details),
        "source": incoming.source or existing.get("source") or "webui",
        "confidence": max(float(existing.get("confidence") or 0.0), incoming.confidence),
        "sensitivity": _max_sensitivity(str(existing.get("sensitivity") or "normal"), incoming.sensitivity),
        "tags": _dedupe([*(existing.get("tags") or []), *incoming.tags]),
        "links": _dedupe([*(existing.get("links") or []), *incoming.links]),
        "mentions": int(existing.get("mentions") or 1) + 1,
        "updated_at": now,
    }


def _record_from_dict(item: dict[str, Any]) -> EntityRecord:
    return EntityRecord(
        entity_id=str(item.get("entity_id") or _entity_id(item.get("kind", "account"), item.get("name", ""))),
        kind=_kind(str(item.get("kind") or "account")),
        name=str(item.get("name") or ""),
        aliases=[str(value) for value in item.get("aliases", []) if str(value).strip()] if isinstance(item.get("aliases"), list) else [],
        details=item.get("details") if isinstance(item.get("details"), dict) else {},
        source=str(item.get("source") or "webui"),
        workspace=str(item.get("workspace") or ""),
        confidence=float(item.get("confidence") or 0.0),
        sensitivity=str(item.get("sensitivity") or "normal"),
        tags=[str(value) for value in item.get("tags", []) if str(value).strip()] if isinstance(item.get("tags"), list) else [],
        links=[str(value) for value in item.get("links", []) if str(value).strip()] if isinstance(item.get("links"), list) else [],
        mentions=int(item.get("mentions") or 1),
        created_at=int(item.get("created_at") or 0),
        updated_at=int(item.get("updated_at") or 0),
    )


def _safe_details(details: dict[str, Any]) -> dict[str, Any]:
    redacted = redact.content(secret_hygiene.safe_context(details))
    return redacted if isinstance(redacted, dict) else {}


def _clean_excerpt(text: str) -> str:
    clean = " ".join(redact.text(secret_hygiene.safe_context(str(text or ""))).split())
    return clean[:MAX_EXCERPT_CHARS].rstrip()


def _clean_name(value: str) -> str:
    text = " ".join(redact.text(str(value or "")).split())
    text = re.split(
        r"\s+\b(?:and|but|that|where|because|when|with|next|around|has|have|is|are|was|were)\b|[,!?;]",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    text = text.strip(" \t\r\n\"'`.,:()[]{}")
    return text[:96].rstrip()


def _compact_details(details: dict[str, Any]) -> str:
    if not details:
        return ""
    pieces = []
    for key in ("platform", "type", "role", "relationship", "url"):
        value = details.get(key)
        if value:
            pieces.append(f"{key}={value}")
    return f"; {'; '.join(pieces[:4])}" if pieces else ""


def _kind(value: str) -> str:
    clean = str(value or "").strip().lower()
    return clean if clean in VALID_KINDS else "account"


def _kind_from_label(label: str) -> str:
    label = label.lower()
    if label in {"person", "client", "customer", "friend", "partner", "contact"}:
        return "person"
    if label in {"business", "company", "store", "startup"}:
        return "business"
    if label in {"channel", "server"}:
        return "channel"
    if label in {"account", "profile"}:
        return "account"
    return "brand"


def _sensitivity(candidate: dict[str, Any]) -> str:
    name = str(candidate.get("name") or "")
    details = candidate.get("details") if isinstance(candidate.get("details"), dict) else {}
    if EMAIL_RE.search(name) or details.get("platform") == "email":
        return "private"
    return "normal"


def _max_sensitivity(left: str, right: str) -> str:
    order = {"normal": 0, "private": 1}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for candidate in candidates:
        name = _clean_name(str(candidate.get("name") or ""))
        kind = _kind(str(candidate.get("kind") or ""))
        if not name:
            continue
        key = f"{kind}:{_norm(name)}"
        if key in seen:
            continue
        seen.add(key)
        candidate = dict(candidate)
        candidate["kind"] = kind
        candidate["name"] = name
        out.append(candidate)
    return out


def _dedupe(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = str(item or "").strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _entity_id(kind: str, name: str) -> str:
    key = f"{_kind(kind)}:{_norm(name)}"
    return "ent_" + hashlib.sha1(key.encode("utf-8", errors="replace")).hexdigest()[:14]


def _norm(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9@/._+-]+", str(value or "").lower()))


def _clean_token(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean[:limit].rstrip()


def _format_time(value: int) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))
    except Exception:
        return "unknown"


def _now() -> int:
    return int(time.time())
