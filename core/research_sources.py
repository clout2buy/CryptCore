"""Reusable research source registry."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import session, settings


SCHEMA_VERSION = 1
URL_RE = re.compile(r"https?://[^\s<>)\"']+", re.I)


@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    cwd: str
    url: str
    title: str = ""
    summary: str = ""
    quotes: list[str] = field(default_factory=list)
    published_at: str = ""
    trust: str = "unknown"
    notes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sources_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "research" / "sources.json"


def add_source(
    cwd: str | Path,
    *,
    url: str,
    title: str = "",
    summary: str = "",
    quotes: list[str] | None = None,
    published_at: str = "",
    trust: str = "unknown",
    notes: list[str] | None = None,
    tags: list[str] | None = None,
) -> ResearchSource:
    root = Path(cwd).expanduser().resolve()
    clean_url = _url(url)
    if not clean_url:
        raise ValueError("source url must be http(s)")
    existing = next((row for row in list_sources(root, include_all=True) if row.url == clean_url), None)
    now = _now()
    source = ResearchSource(
        source_id=existing.source_id if existing else "src_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        url=clean_url,
        title=_clean(title or _host_title(clean_url), 200),
        summary=_clean(summary or (existing.summary if existing else ""), 1_500),
        quotes=_quote_list([*(quotes or []), *(existing.quotes if existing else [])]),
        published_at=_clean(published_at or (existing.published_at if existing else ""), 80),
        trust=_trust(trust or (existing.trust if existing else "")),
        notes=_dedupe([*(notes or []), *(existing.notes if existing else [])], 500),
        tags=_dedupe([*(tags or []), *(existing.tags if existing else [])], 80),
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    rows = [row for row in list_sources(root, include_all=True) if row.source_id != source.source_id]
    rows.insert(0, source)
    _write(root, rows)
    return source


def observe_text(cwd: str | Path, text: str, *, tags: list[str] | None = None) -> list[ResearchSource]:
    found = []
    for match in URL_RE.finditer(str(text or "")):
        found.append(add_source(cwd, url=match.group(0), notes=["observed from chat"], tags=tags or ["observed"]))
    return found


def search(cwd: str | Path, query: str, *, limit: int = 8) -> list[ResearchSource]:
    terms = _tokens(query)
    rows = list_sources(cwd, include_all=True, limit=200)
    if not terms:
        return rows[:limit]
    scored = []
    for row in rows:
        haystack = _tokens(" ".join([row.url, row.title, row.summary, " ".join(row.tags), " ".join(row.notes)]))
        overlap = terms & haystack
        if overlap:
            scored.append((len(overlap), row.updated_at, row))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [row for _, _, row in scored[: max(1, limit)]]


def list_sources(cwd: str | Path, *, include_all: bool = False, limit: int = 100) -> list[ResearchSource]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.trust != "rejected"]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_sources(cwd, include_all=True, limit=80)
    return {
        "total": len(rows),
        "trusted": sum(1 for row in rows if row.trust == "trusted"),
        "unknown": sum(1 for row in rows if row.trust == "unknown"),
        "questionable": sum(1 for row in rows if row.trust == "questionable"),
        "sources": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, text: str = "", *, limit: int = 5) -> str:
    rows = search(cwd, text, limit=limit)
    if not rows:
        return ""
    lines = ["# Research Sources"]
    for row in rows:
        quote = f"; quote={row.quotes[0]}" if row.quotes else ""
        lines.append(f"- {row.trust}: {row.title} - {row.url}; {row.summary[:220]}{quote}")
    return "\n".join(lines)


def _read(cwd: str | Path) -> list[ResearchSource]:
    path = sources_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("sources", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                ResearchSource(
                    source_id=str(item.get("source_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    url=str(item.get("url") or ""),
                    title=str(item.get("title") or ""),
                    summary=str(item.get("summary") or ""),
                    quotes=[str(value) for value in item.get("quotes", []) if str(value).strip()],
                    published_at=str(item.get("published_at") or ""),
                    trust=_trust(str(item.get("trust") or "unknown")),
                    notes=[str(value) for value in item.get("notes", []) if str(value).strip()],
                    tags=[str(value) for value in item.get("tags", []) if str(value).strip()],
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.source_id and row.url]


def _write(cwd: str | Path, rows: list[ResearchSource]) -> None:
    path = sources_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "sources": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _url(value: str) -> str:
    clean = str(value or "").strip().rstrip(".,)")
    parsed = urlparse(clean)
    return clean if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _host_title(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or "source"


def _trust(value: str) -> str:
    clean = str(value or "unknown").strip().lower()
    return clean if clean in {"trusted", "unknown", "questionable", "rejected"} else "unknown"


def _quote_list(values: list[str]) -> list[str]:
    out = []
    for value in values:
        words = str(value or "").split()
        if not words:
            continue
        out.append(" ".join(words[:25]))
    return _dedupe(out, 300)[:8]


def _dedupe(values: list[str], limit: int) -> list[str]:
    out = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value, limit)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _tokens(text: str) -> set[str]:
    return {part.lower() for part in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{1,60}", str(text or ""))}


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
