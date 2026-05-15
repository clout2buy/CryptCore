"""Business entity registry for launch and operations work."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import session, settings


SCHEMA_VERSION = 1
VALID_KINDS = {
    "business",
    "offer",
    "product",
    "customer",
    "channel",
    "asset",
    "domain",
    "expense",
    "revenue-stream",
}
MONEY_RE = re.compile(r"\$(?P<amount>[0-9]+(?:\.[0-9]{1,2})?)")
DOMAIN_RE = re.compile(r"\b(?P<domain>[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+)\b", re.I)
NAMED_RE = re.compile(
    r"\b(?P<kind>business|offer|product|customer|client|channel|asset|domain|revenue stream)"
    r"\s+(?:called|named|is|as)\s+(?P<name>[A-Za-z0-9][A-Za-z0-9 &'_.-]{1,90})",
    re.I,
)
SECONDARY_NAMED_RE = re.compile(
    r"\b(?P<kind>offer|product|customer|client|channel|asset|domain|revenue stream)"
    r"\s+(?:called|named|is|as)\s+(?P<name>[A-Za-z0-9][A-Za-z0-9 &'_.-]{1,90})",
    re.I,
)
EXPENSE_RE = re.compile(
    r"\b(?:expense|spent|cost|paid)\b(?:\s+\$?(?P<amount>[0-9]+(?:\.[0-9]{1,2})?))?"
    r"(?:\s+(?:for|on)\s+(?P<name>[A-Za-z0-9][A-Za-z0-9 &'_.-]{1,80}))?",
    re.I,
)
CHANNEL_RE = re.compile(r"\b(?P<name>reddit|email|youtube|tiktok|instagram|x|twitter|discord|slack|seo|ads)\b", re.I)


@dataclass(frozen=True)
class BusinessEntity:
    entity_id: str
    kind: str
    name: str
    status: str = "active"
    value: float = 0.0
    currency: str = "USD"
    details: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    source: str = "webui"
    workspace: str = ""
    mentions: int = 1
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BusinessEntityObservation:
    changed: bool
    records: list[BusinessEntity] = field(default_factory=list)
    count: int = 0


def state_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "business" / "entities.json"


def markdown_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "business" / "BUSINESS_REGISTRY.md"


def upsert_entity(
    cwd: str | Path,
    kind: str,
    name: str,
    *,
    status: str = "active",
    value: float = 0.0,
    currency: str = "USD",
    details: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    links: list[str] | None = None,
    source: str = "webui",
) -> tuple[BusinessEntity, bool]:
    root = Path(cwd).expanduser().resolve()
    ensure_store(root)
    clean_kind = _kind(kind)
    clean_name = _clean(name, 120)
    if not clean_name:
        raise ValueError("business entity name cannot be empty")
    now = _now()
    incoming = BusinessEntity(
        entity_id=_entity_id(clean_kind, clean_name),
        kind=clean_kind,
        name=clean_name,
        status=_clean(status, 40) or "active",
        value=round(float(value or 0.0), 2),
        currency=_clean(currency, 8).upper() or "USD",
        details=_safe_details(details or {}),
        tags=_dedupe([clean_kind, *(tags or [])]),
        links=_dedupe(links or []),
        source=_clean(source, 40) or "webui",
        workspace=str(root),
        created_at=now,
        updated_at=now,
    )
    state = _read_state(root)
    rows = []
    changed = False
    merged = incoming
    found = False
    for item in state.get("entities", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("entity_id") or "") == incoming.entity_id:
            found = True
            data = _merge(item, incoming)
            changed = changed or data != item
            merged = _record(data)
            rows.append(data)
        else:
            rows.append(item)
    if not found:
        rows.insert(0, incoming.to_dict())
        changed = True
    if changed:
        state["schema"] = SCHEMA_VERSION
        state["workspace"] = str(root)
        state["updated_at"] = now
        state["entities"] = sorted(rows, key=lambda row: int(row.get("updated_at") or 0), reverse=True)[:500]
        _write_state(root, state)
        _write_markdown(root, state)
    return merged, changed


def observe_text(cwd: str | Path, text: str, *, source: str = "webui") -> BusinessEntityObservation:
    clean = _clean(text, 2_000)
    if not clean or not _looks_business(clean):
        return BusinessEntityObservation(False, count=len(list_entities(cwd)))
    changed = False
    records: list[BusinessEntity] = []
    for candidate in _extract_candidates(clean):
        record, did_change = upsert_entity(cwd, source=source, **candidate)
        records.append(record)
        changed = changed or did_change
    return BusinessEntityObservation(changed, records=records, count=len(list_entities(cwd)))


def list_entities(cwd: str | Path, *, kind: str = "", query: str = "", limit: int = 120) -> list[BusinessEntity]:
    ensure_store(cwd)
    wanted = _kind(kind) if kind else ""
    needle = _norm(query)
    rows: list[BusinessEntity] = []
    for item in _read_state(cwd).get("entities", []):
        if not isinstance(item, dict):
            continue
        record = _record(item)
        if wanted and record.kind != wanted:
            continue
        haystack = _norm(" ".join([record.name, record.kind, *record.tags, json.dumps(record.details, sort_keys=True)]))
        if needle and needle not in haystack:
            continue
        rows.append(record)
    rows.sort(key=lambda record: (record.updated_at, record.mentions), reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path, *, preview: int = 16) -> dict[str, Any]:
    all_rows = list_entities(cwd, limit=500)
    counts: dict[str, int] = {}
    value_totals: dict[str, float] = {}
    for row in all_rows:
        counts[row.kind] = counts.get(row.kind, 0) + 1
        if row.kind in {"expense", "revenue-stream"}:
            value_totals[row.kind] = round(value_totals.get(row.kind, 0.0) + row.value, 2)
    return {
        "path": str(state_path(cwd)),
        "markdownPath": str(markdown_path(cwd)),
        "count": len(all_rows),
        "kindCounts": counts,
        "valueTotals": value_totals,
        "preview": [row.to_dict() for row in all_rows[: max(1, preview)]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 12) -> str:
    rows = list_entities(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Business Entity Registry"]
    for row in rows:
        value = f" {row.currency} {row.value:.2f}" if row.value else ""
        detail = _compact_details(row.details)
        lines.append(f"- [{row.kind}] {row.name}{value}; status={row.status}{detail}")
    return "\n".join(lines)


def ensure_store(cwd: str | Path) -> Path:
    root = Path(cwd).expanduser().resolve()
    path = state_path(root)
    if not path.exists():
        state = {"schema": SCHEMA_VERSION, "workspace": str(root), "updated_at": _now(), "entities": []}
        _write_state(root, state)
        _write_markdown(root, state)
    return path


def _extract_candidates(text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    excerpt = _clean(text, 500)
    for match in NAMED_RE.finditer(text):
        kind = _kind(match.group("kind"))
        if kind == "client":
            kind = "customer"
        candidates.append(
            {
                "kind": kind,
                "name": _trim_embedded_entity(match.group("name")),
                "details": {"excerpt": excerpt},
                "tags": ["business", kind],
            }
        )
    for match in SECONDARY_NAMED_RE.finditer(text):
        kind = _kind(match.group("kind"))
        if kind == "client":
            kind = "customer"
        candidates.append(
            {
                "kind": kind,
                "name": _trim_embedded_entity(match.group("name")),
                "details": {"excerpt": excerpt},
                "tags": ["business", kind],
            }
        )
    for match in DOMAIN_RE.finditer(text):
        candidates.append(
            {
                "kind": "domain",
                "name": match.group("domain"),
                "details": {"excerpt": excerpt},
                "tags": ["business", "domain"],
            }
        )
    for match in EXPENSE_RE.finditer(text):
        amount = float(match.group("amount") or 0.0)
        name = match.group("name") or "Unlabeled expense"
        candidates.append(
            {
                "kind": "expense",
                "name": name,
                "value": amount,
                "details": {"excerpt": excerpt},
                "tags": ["business", "expense"],
            }
        )
    if "revenue" in text.lower() or "income" in text.lower():
        money = MONEY_RE.search(text)
        candidates.append(
            {
                "kind": "revenue-stream",
                "name": _clean(text, 70),
                "value": float(money.group("amount")) if money else 0.0,
                "details": {"excerpt": excerpt},
                "tags": ["business", "revenue"],
            }
        )
    for match in CHANNEL_RE.finditer(text):
        candidates.append(
            {
                "kind": "channel",
                "name": match.group("name").lower(),
                "details": {"platform": match.group("name").lower(), "excerpt": excerpt},
                "tags": ["business", "channel"],
            }
        )
    return _dedupe_candidates(candidates)


def _looks_business(text: str) -> bool:
    lower = text.lower()
    return any(
        term in lower
        for term in (
            "business",
            "offer",
            "product",
            "customer",
            "client",
            "domain",
            "revenue",
            "income",
            "expense",
            "spent",
            "channel",
            "launch",
            "sales",
        )
    )


def _read_state(cwd: str | Path) -> dict[str, Any]:
    path = state_path(cwd)
    if not path.exists():
        return {"schema": SCHEMA_VERSION, "workspace": str(Path(cwd).expanduser().resolve()), "entities": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": SCHEMA_VERSION, "workspace": str(Path(cwd).expanduser().resolve()), "entities": []}
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return {"schema": SCHEMA_VERSION, "workspace": str(Path(cwd).expanduser().resolve()), "entities": []}
    return data


def _write_state(cwd: str | Path, state: dict[str, Any]) -> None:
    path = state_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    settings.restrict_file_permissions(path)


def _write_markdown(cwd: str | Path, state: dict[str, Any]) -> None:
    rows = [_record(item) for item in state.get("entities", []) if isinstance(item, dict)]
    lines = ["# Business Registry", ""]
    if not rows:
        lines.append("No business entities logged yet.")
    for kind in sorted({row.kind for row in rows}):
        lines.extend(["", f"## {kind.title()}"])
        for row in [item for item in rows if item.kind == kind]:
            value = f" - {row.currency} {row.value:.2f}" if row.value else ""
            lines.append(f"- **{row.name}** ({row.status}){value}")
            detail = _compact_details(row.details)
            if detail:
                lines.append(f"  - {detail.lstrip('; ')}")
    path = markdown_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    settings.restrict_file_permissions(path)


def _merge(existing: dict[str, Any], incoming: BusinessEntity) -> dict[str, Any]:
    data = dict(existing)
    data["mentions"] = int(data.get("mentions") or 1) + 1
    data["status"] = incoming.status or str(data.get("status") or "active")
    data["value"] = incoming.value or float(data.get("value") or 0.0)
    data["currency"] = incoming.currency or str(data.get("currency") or "USD")
    data["details"] = {**(data.get("details") if isinstance(data.get("details"), dict) else {}), **incoming.details}
    data["tags"] = _dedupe([*(data.get("tags") or []), *incoming.tags])
    data["links"] = _dedupe([*(data.get("links") or []), *incoming.links])
    data["updated_at"] = incoming.updated_at
    return data


def _record(item: dict[str, Any]) -> BusinessEntity:
    return BusinessEntity(
        entity_id=str(item.get("entity_id") or ""),
        kind=_kind(str(item.get("kind") or "business")),
        name=_clean(str(item.get("name") or ""), 120),
        status=_clean(str(item.get("status") or "active"), 40) or "active",
        value=round(float(item.get("value") or 0.0), 2),
        currency=_clean(str(item.get("currency") or "USD"), 8).upper() or "USD",
        details=item.get("details") if isinstance(item.get("details"), dict) else {},
        tags=[str(value) for value in item.get("tags", []) if str(value).strip()],
        links=[str(value) for value in item.get("links", []) if str(value).strip()],
        source=str(item.get("source") or "webui"),
        workspace=str(item.get("workspace") or ""),
        mentions=int(item.get("mentions") or 1),
        created_at=int(item.get("created_at") or 0),
        updated_at=int(item.get("updated_at") or 0),
    )


def _entity_id(kind: str, name: str) -> str:
    digest = hashlib.sha1(f"{kind}:{_norm(name)}".encode("utf-8")).hexdigest()[:12]
    return f"biz_{digest}"


def _kind(value: str) -> str:
    clean = str(value or "business").strip().lower().replace("_", "-").replace(" ", "-")
    if clean == "client":
        clean = "customer"
    if clean not in VALID_KINDS:
        return "business"
    return clean


def _safe_details(details: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in details.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[_clean(str(key), 60)] = value if not isinstance(value, str) else _clean(value, 600)
    return out


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value, 80)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in candidates:
        key = (_kind(str(item.get("kind") or "")), _norm(str(item.get("name") or "")))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _trim_embedded_entity(value: str) -> str:
    clean = _clean(value, 120)
    for marker in (" has ", " with ", " and ", " plus "):
        index = clean.lower().find(marker)
        if index > 0:
            return clean[:index].strip()
    return clean


def _compact_details(details: dict[str, Any]) -> str:
    if not details:
        return ""
    parts = [f"{key}={value}" for key, value in details.items() if value not in ("", None)]
    return "; " + "; ".join(parts[:3]) if parts else ""


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _now() -> int:
    return int(time.time())
