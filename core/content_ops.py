"""Content operations planner with approval-gated drafts and metrics."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import external_drafts, session, settings


SCHEMA_VERSION = 1
CONTENT_RE = re.compile(r"\b(content|post|posts|tweet|reddit|youtube|video|script|thumbnail|newsletter|blog|launch copy)\b", re.I)


@dataclass(frozen=True)
class ContentPiece:
    piece_id: str
    kind: str
    channel: str
    title: str
    status: str = "draft"
    approval_required: bool = True
    draft_id: str = ""
    content: str = ""
    scheduled_at: int = 0
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentCampaign:
    campaign_id: str
    cwd: str
    title: str
    goal: str
    audience: str = ""
    status: str = "active"
    channels: list[str] = field(default_factory=list)
    pieces: list[ContentPiece] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "pieces": [asdict(piece) for piece in self.pieces]}


@dataclass(frozen=True)
class ContentDecision:
    campaign: ContentCampaign | None
    created: bool = False
    reason: str = ""


def campaigns_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "content_ops" / "campaigns.json"


def ensure_for_prompt(cwd: str | Path, text: str) -> ContentDecision:
    if not is_content_request(text):
        return ContentDecision(None, False, "not a content request")
    root = Path(cwd).expanduser().resolve()
    title = _title_from_prompt(text)
    existing = next((row for row in list_campaigns(root) if row.title.lower() == title.lower()), None)
    if existing:
        return ContentDecision(existing, False, "matched existing content campaign")
    return ContentDecision(plan(root, text, title=title), True, "created content campaign")


def plan(
    cwd: str | Path,
    prompt: str,
    *,
    title: str = "",
    audience: str = "",
    channels: list[str] | None = None,
) -> ContentCampaign:
    root = Path(cwd).expanduser().resolve()
    clean_prompt = _clean(prompt, 2_000)
    selected_channels = _channels(channels or _channels_from_prompt(clean_prompt))
    clean_title = _clean(title, 140) or _title_from_prompt(clean_prompt)
    pieces = []
    for channel in selected_channels:
        pieces.extend(_pieces_for_channel(root, channel, clean_title, clean_prompt))
    campaign = ContentCampaign(
        campaign_id="content_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        title=clean_title,
        goal=clean_prompt,
        audience=_clean(audience, 180),
        channels=selected_channels,
        pieces=pieces,
        created_at=_now(),
        updated_at=_now(),
    )
    rows = [row for row in list_campaigns(root, include_all=True) if row.title.lower() != campaign.title.lower()]
    rows.insert(0, campaign)
    _write(root, rows)
    return campaign


def record_metric(
    cwd: str | Path,
    piece_id: str,
    *,
    views: float = 0,
    clicks: float = 0,
    leads: float = 0,
    revenue: float = 0,
) -> ContentCampaign:
    root = Path(cwd).expanduser().resolve()
    rows = []
    updated: ContentCampaign | None = None
    for campaign in list_campaigns(root, include_all=True):
        new_pieces = []
        changed = False
        for piece in campaign.pieces:
            if piece.piece_id != piece_id:
                new_pieces.append(piece)
                continue
            metrics = dict(piece.metrics)
            for key, value in {"views": views, "clicks": clicks, "leads": leads, "revenue": revenue}.items():
                if value:
                    metrics[key] = round(float(metrics.get(key, 0.0)) + float(value), 2)
            new_pieces.append(replace(piece, metrics=metrics, status="measured"))
            changed = True
        if changed:
            updated = replace(campaign, pieces=new_pieces, updated_at=_now())
            rows.append(updated)
        else:
            rows.append(campaign)
    if updated is None:
        raise KeyError(f"unknown content piece: {piece_id}")
    _write(root, rows)
    return updated


def list_campaigns(cwd: str | Path, *, include_all: bool = False, limit: int = 50) -> list[ContentCampaign]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status in {"active", "paused"}]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_campaigns(cwd, include_all=True, limit=30)
    pieces = [piece for row in rows for piece in row.pieces]
    return {
        "total": len(rows),
        "active": sum(1 for row in rows if row.status == "active"),
        "pieces": len(pieces),
        "approvalRequired": sum(1 for piece in pieces if piece.approval_required),
        "measured": sum(1 for piece in pieces if piece.metrics),
        "campaigns": [row.to_dict() for row in rows[:10]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 4) -> str:
    rows = list_campaigns(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Content Operations"]
    for row in rows:
        pending = sum(1 for piece in row.pieces if piece.status in {"draft", "planned"})
        lines.append(f"- {row.title}: channels={', '.join(row.channels)}; pieces={len(row.pieces)}; pending={pending}")
    return "\n".join(lines)


def is_content_request(text: str) -> bool:
    return bool(CONTENT_RE.search(str(text or "")))


def _pieces_for_channel(root: Path, channel: str, title: str, prompt: str) -> list[ContentPiece]:
    specs = {
        "reddit": [("post", "Reddit discussion post"), ("comment", "Follow-up comment")],
        "x": [("post", "Short launch post"), ("thread", "Three-part thread")],
        "youtube": [("script", "Short video script"), ("thumbnail", "Thumbnail concept")],
        "email": [("email", "Launch email"), ("followup", "Lead follow-up")],
        "blog": [("article", "Search-focused article")],
    }.get(channel, [("post", "Channel post")])
    pieces = []
    for kind, label in specs:
        content = f"{label} for {title}. Source goal: {prompt}"
        draft = external_drafts.create_draft(
            root,
            kind=f"{channel}-{kind}",
            title=f"{label}: {title}",
            target=channel,
            content=content,
            source_prompt=prompt,
            risk="high",
        )
        pieces.append(
            ContentPiece(
                piece_id="piece_" + uuid.uuid4().hex[:10],
                kind=kind,
                channel=channel,
                title=f"{label}: {title}",
                status="draft",
                approval_required=True,
                draft_id=draft.draft_id,
                content=content,
            )
        )
    return pieces


def _read(cwd: str | Path) -> list[ContentCampaign]:
    path = campaigns_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("campaigns", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(_campaign_from_dict(item))
        except Exception:
            continue
    return [row for row in rows if row.campaign_id and row.cwd]


def _write(cwd: str | Path, rows: list[ContentCampaign]) -> None:
    path = campaigns_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "campaigns": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _campaign_from_dict(item: dict[str, Any]) -> ContentCampaign:
    pieces = [
        ContentPiece(
            piece_id=str(raw.get("piece_id") or ""),
            kind=str(raw.get("kind") or "post"),
            channel=str(raw.get("channel") or ""),
            title=str(raw.get("title") or ""),
            status=str(raw.get("status") or "draft"),
            approval_required=bool(raw.get("approval_required", True)),
            draft_id=str(raw.get("draft_id") or ""),
            content=str(raw.get("content") or ""),
            scheduled_at=int(raw.get("scheduled_at") or 0),
            metrics={str(k): float(v) for k, v in dict(raw.get("metrics") or {}).items()},
        )
        for raw in item.get("pieces", [])
        if isinstance(raw, dict)
    ]
    return ContentCampaign(
        campaign_id=str(item.get("campaign_id") or ""),
        cwd=str(item.get("cwd") or ""),
        title=str(item.get("title") or ""),
        goal=str(item.get("goal") or ""),
        audience=str(item.get("audience") or ""),
        status=str(item.get("status") or "active"),
        channels=[str(value) for value in item.get("channels", []) if str(value).strip()],
        pieces=pieces,
        created_at=int(item.get("created_at") or 0),
        updated_at=int(item.get("updated_at") or 0),
    )


def _channels_from_prompt(prompt: str) -> list[str]:
    lower = prompt.lower()
    channels = []
    if "reddit" in lower:
        channels.append("reddit")
    if "twitter" in lower or "x " in lower or "tweet" in lower:
        channels.append("x")
    if "youtube" in lower or "video" in lower or "thumbnail" in lower:
        channels.append("youtube")
    if "email" in lower or "newsletter" in lower:
        channels.append("email")
    if "blog" in lower or "article" in lower:
        channels.append("blog")
    return channels or ["reddit", "x", "email"]


def _channels(values: list[str]) -> list[str]:
    allowed = {"reddit", "x", "youtube", "email", "blog"}
    out = []
    for value in values:
        clean = str(value or "").strip().lower()
        if clean in allowed and clean not in out:
            out.append(clean)
    return out or ["reddit", "x", "email"]


def _title_from_prompt(prompt: str) -> str:
    clean = _clean(prompt, 90)
    clean = re.sub(r"^(plan|create|make|build|draft)\s+(a\s+)?", "", clean, flags=re.I).strip()
    return clean[:1].upper() + clean[1:] if clean else "Content Campaign"


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
