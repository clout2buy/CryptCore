"""Approval-first public posting workflow."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import external_drafts, research_sources, session, settings


SCHEMA_VERSION = 1
PLATFORMS = {"reddit", "x", "twitter", "linkedin", "youtube", "blog", "discord"}
STATUSES = {"draft", "needs-citations", "pending-approval", "approved", "published", "cancelled"}
CLAIM_RE = re.compile(r"\b(\d+%|\$\d+|\b\d+x\b|guarantee|proven|best|latest|study|research|according to)\b", re.I)


@dataclass(frozen=True)
class PublicPost:
    post_id: str
    cwd: str
    platform: str
    title: str
    content: str
    status: str = "draft"
    citations: list[str] = field(default_factory=list)
    draft_id: str = ""
    checks: list[str] = field(default_factory=list)
    approval_note: str = ""
    published_url: str = ""
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def posts_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "public_posting" / "posts.json"


def create_post(
    cwd: str | Path,
    *,
    platform: str,
    content: str,
    title: str = "",
    citations: list[str] | None = None,
) -> PublicPost:
    root = Path(cwd).expanduser().resolve()
    clean_content = _clean(content, 5_000)
    if not clean_content:
        raise ValueError("post content cannot be empty")
    clean_platform = _platform(platform)
    cite_rows = _citation_urls(root, citations or [])
    checks = approval_checks(clean_content, cite_rows)
    status = "needs-citations" if any(check.startswith("FAIL") for check in checks) else "pending-approval"
    draft = external_drafts.create_draft(
        root,
        kind=f"{clean_platform}-public-post",
        title=_clean(title, 160) or f"{clean_platform} public post",
        target=clean_platform,
        content=clean_content,
        source_prompt="public posting flow",
        risk="high",
    )
    now = _now()
    post = PublicPost(
        post_id="post_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        platform=clean_platform,
        title=_clean(title, 160) or f"{clean_platform} public post",
        content=clean_content,
        status=status,
        citations=cite_rows,
        draft_id=draft.draft_id,
        checks=checks,
        created_at=now,
        updated_at=now,
    )
    rows = list_posts(root, include_all=True)
    rows.insert(0, post)
    _write(root, rows)
    return post


def approval_checks(content: str, citations: list[str]) -> list[str]:
    checks = ["PASS external draft required", "PASS approval required before publishing"]
    if CLAIM_RE.search(content):
        checks.append("PASS citations present" if citations else "FAIL factual/performance claim needs citation")
    else:
        checks.append("PASS no citation-heavy claim detected")
    if len(content) > 2_800:
        checks.append("WARN long post may need platform trimming")
    return checks


def approve(cwd: str | Path, post_id: str, *, note: str = "") -> PublicPost:
    return _update(cwd, post_id, status="approved", approval_note=note)


def mark_published(cwd: str | Path, post_id: str, *, url: str) -> PublicPost:
    clean_url = str(url or "").strip()
    if not clean_url.startswith(("http://", "https://")):
        raise ValueError("published url must be http(s)")
    return _update(cwd, post_id, status="published", published_url=clean_url)


def list_posts(cwd: str | Path, *, include_all: bool = False, limit: int = 80) -> list[PublicPost]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status != "cancelled"]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_posts(cwd, include_all=True, limit=50)
    return {
        "total": len(rows),
        "pending": sum(1 for row in rows if row.status == "pending-approval"),
        "needsCitations": sum(1 for row in rows if row.status == "needs-citations"),
        "published": sum(1 for row in rows if row.status == "published"),
        "posts": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_posts(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Public Posting Flow"]
    for row in rows:
        lines.append(
            f"- {row.status} {row.platform}: {row.title}; citations={len(row.citations)}; draft={row.draft_id}; publish only after approval"
        )
    return "\n".join(lines)


def _update(cwd: str | Path, post_id: str, **values: Any) -> PublicPost:
    root = Path(cwd).expanduser().resolve()
    rows = []
    updated: PublicPost | None = None
    for post in list_posts(root, include_all=True):
        if post.post_id != post_id:
            rows.append(post)
            continue
        updated = replace(
            post,
            status=_status(str(values.get("status") or post.status)),
            approval_note=_clean(str(values.get("approval_note") or post.approval_note), 1_000),
            published_url=_clean(str(values.get("published_url") or post.published_url), 500),
            updated_at=_now(),
        )
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown public post: {post_id}")
    _write(root, rows)
    return updated


def _citation_urls(cwd: Path, citations: list[str]) -> list[str]:
    urls = []
    existing = {row.url for row in research_sources.list_sources(cwd, include_all=True, limit=200)}
    for value in citations:
        clean = str(value or "").strip()
        if not clean:
            continue
        if clean.startswith(("http://", "https://")):
            if clean not in existing:
                research_sources.add_source(cwd, url=clean, tags=["public-post-citation"])
            urls.append(clean)
    return _dedupe(urls, 500)


def _read(cwd: str | Path) -> list[PublicPost]:
    path = posts_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("posts", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                PublicPost(
                    post_id=str(item.get("post_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    platform=_platform(str(item.get("platform") or "reddit")),
                    title=str(item.get("title") or ""),
                    content=str(item.get("content") or ""),
                    status=_status(str(item.get("status") or "draft")),
                    citations=[str(value) for value in item.get("citations", []) if str(value).strip()],
                    draft_id=str(item.get("draft_id") or ""),
                    checks=[str(value) for value in item.get("checks", []) if str(value).strip()],
                    approval_note=str(item.get("approval_note") or ""),
                    published_url=str(item.get("published_url") or ""),
                    created_at=int(item.get("created_at") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.post_id and row.cwd]


def _write(cwd: str | Path, rows: list[PublicPost]) -> None:
    path = posts_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "posts": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _platform(value: str) -> str:
    clean = str(value or "reddit").strip().lower()
    if clean == "twitter":
        clean = "x"
    return clean if clean in PLATFORMS else "reddit"


def _status(value: str) -> str:
    clean = str(value or "draft").strip().lower()
    return clean if clean in STATUSES else "draft"


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


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
