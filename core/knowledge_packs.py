"""Portable knowledge packs for agents and long-running workers."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import asset_library, business_crm, context_packs, redact, research_sources, session, settings


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class KnowledgePackManifest:
    pack_id: str
    title: str
    query: str
    path: str
    item_count: int = 0
    estimated_tokens: int = 0
    omitted: int = 0
    sources: dict[str, int] | None = None
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def packs_dir(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "knowledge_packs"


def manifest_path(cwd: str | Path) -> Path:
    return packs_dir(cwd) / "packs.json"


def build_pack(
    cwd: str | Path,
    *,
    title: str,
    query: str = "",
    budget_tokens: int = 3_200,
) -> KnowledgePackManifest:
    root = Path(cwd).expanduser().resolve()
    clean_title = _clean(title, 140) or "Knowledge Pack"
    pack = context_packs.build(root, query or clean_title, budget_tokens=budget_tokens)
    assets = asset_library.snapshot(root)
    crm = business_crm.snapshot(root)
    sources = research_sources.snapshot(root)
    body = _render_markdown(clean_title, pack, assets, crm, sources)
    pack_id = "kpack_" + _slug(clean_title)[:40] + "_" + str(int(time.time()))
    path = packs_dir(root) / f"{pack_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    settings.restrict_file_permissions(path)
    manifest = KnowledgePackManifest(
        pack_id=pack_id,
        title=clean_title,
        query=pack.query,
        path=str(path),
        item_count=len(pack.items),
        estimated_tokens=pack.estimated_tokens,
        omitted=pack.omitted,
        sources=_source_counts(pack, assets, crm, sources),
        created_at=int(time.time()),
    )
    manifests = [manifest, *[item for item in list_packs(root, limit=100) if item.pack_id != pack_id]][:100]
    _write_manifest(root, manifests)
    return manifest


def list_packs(cwd: str | Path, *, limit: int = 30) -> list[KnowledgePackManifest]:
    path = manifest_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("packs", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                KnowledgePackManifest(
                    pack_id=str(item.get("pack_id") or ""),
                    title=str(item.get("title") or ""),
                    query=str(item.get("query") or ""),
                    path=str(item.get("path") or ""),
                    item_count=int(item.get("item_count") or 0),
                    estimated_tokens=int(item.get("estimated_tokens") or 0),
                    omitted=int(item.get("omitted") or 0),
                    sources=dict(item.get("sources") or {}),
                    created_at=int(item.get("created_at") or 0),
                )
            )
        except Exception:
            continue
    rows = [row for row in rows if row.pack_id and row.path]
    rows.sort(key=lambda row: row.created_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    packs = list_packs(cwd, limit=30)
    return {
        "schema": SCHEMA_VERSION,
        "total": len(packs),
        "latest": packs[0].to_dict() if packs else None,
        "packs": [pack.to_dict() for pack in packs[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 4) -> str:
    packs = list_packs(cwd, limit=limit)
    if not packs:
        return ""
    lines = ["# Knowledge Packs"]
    for pack in packs:
        lines.append(f"- {pack.title}: {pack.item_count} item(s), tokens~{pack.estimated_tokens}, path={pack.path}")
    return "\n".join(lines)


def _render_markdown(title: str, pack: context_packs.ContextPack, assets: dict[str, Any], crm: dict[str, Any], sources: dict[str, Any]) -> str:
    lines = [
        f"# {redact.text(title)}",
        "",
        f"- Query: {redact.text(pack.query or title)}",
        f"- Estimated tokens: {pack.estimated_tokens}",
        f"- Omitted candidates: {pack.omitted}",
        f"- Built: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        pack.text or "No runtime context selected.",
        "",
        "## Reusable Assets",
    ]
    for asset in (assets.get("assets") or [])[:12]:
        hints = "; ".join((asset.get("reuse_hints") or [])[:2])
        lines.append(f"- [{asset.get('kind')}] {asset.get('rel_path')}: {asset.get('purpose') or hints}")
    if not (assets.get("assets") or []):
        lines.append("- No reusable assets indexed yet.")
    lines.extend(["", "## CRM Snapshot"])
    lines.append(
        f"- contacts={crm.get('contacts', 0)} leads={crm.get('leads', 0)} customers={crm.get('customers', 0)} pipeline=${float(crm.get('pipelineValueUsd') or 0):.2f}"
    )
    for contact in (crm.get("contactPreview") or [])[:8]:
        lines.append(f"- {contact.get('status')} {contact.get('name')}; next={contact.get('next_action') or 'none'}")
    lines.extend(["", "## Research Sources"])
    for source in (sources.get("sources") or [])[:10]:
        lines.append(f"- {source.get('title') or source.get('url')}: {source.get('url')}")
    if not (sources.get("sources") or []):
        lines.append("- No research sources saved yet.")
    lines.append("")
    return "\n".join(redact.text(line) for line in lines)


def _source_counts(pack: context_packs.ContextPack, assets: dict[str, Any], crm: dict[str, Any], sources: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in pack.items:
        counts[item.section] = counts.get(item.section, 0) + 1
    counts["Assets"] = int(assets.get("total") or 0)
    counts["CRM Contacts"] = int(crm.get("contacts") or 0)
    counts["Research Sources"] = int(sources.get("total") or 0)
    return counts


def _write_manifest(cwd: str | Path, packs: list[KnowledgePackManifest]) -> None:
    path = manifest_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "packs": [pack.to_dict() for pack in packs]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(value or "knowledge-pack").lower()).strip("-") or "knowledge-pack"


def _clean(value: str, limit: int) -> str:
    clean = " ".join(redact.text(str(value or "")).split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
