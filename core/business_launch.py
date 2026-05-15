"""Business launch autopilot tying missions, site work, revenue, and approvals."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import business_mission, office_layer, revenue_ops, session, settings, website_pipeline, work_threads


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LaunchStage:
    key: str
    title: str
    status: str = "pending"
    owner: str = "Crypt"
    approval_required: bool = False
    artifact: str = ""


@dataclass(frozen=True)
class BusinessLaunch:
    launch_id: str
    cwd: str
    title: str
    request: str
    goal_id: str
    thread_id: str
    pipeline_id: str = ""
    revenue_target_id: str = ""
    office_artifact_id: str = ""
    approval_gates: list[str] = field(default_factory=list)
    stages: list[LaunchStage] = field(default_factory=list)
    status: str = "active"
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "stages": [asdict(stage) for stage in self.stages]}


@dataclass(frozen=True)
class LaunchDecision:
    launch: BusinessLaunch | None
    created: bool = False
    reason: str = ""


def launches_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "business_launch" / "launches.json"


def ensure_for_prompt(cwd: str | Path, text: str) -> LaunchDecision:
    if not _looks_like_launch_request(text):
        return LaunchDecision(None, False, "not a business launch request")
    root = Path(cwd).expanduser().resolve()
    title = _title_from_request(text)
    existing = next((row for row in list_launches(root) if row.title.lower() == title.lower()), None)
    if existing:
        return LaunchDecision(existing, False, "matched existing business launch")
    return LaunchDecision(start(root, text, title=title), True, "created business launch autopilot")


def start(
    cwd: str | Path,
    request: str,
    *,
    title: str = "",
    target_revenue: float = 1_000.0,
    cadence: str = "weekly",
) -> BusinessLaunch:
    root = Path(cwd).expanduser().resolve()
    clean_request = _clean(request, 2_000)
    clean_title = _clean(title, 140) or _title_from_request(clean_request)
    goal, thread = business_mission.create_business_mission(root, clean_request)
    pipeline = website_pipeline.create_pipeline(
        root,
        f"Build the launch page for {clean_title}. {clean_request}",
        title=f"{clean_title} launch site",
        audience="first viable customer segment",
        aesthetic_direction="clean, credible, conversion-focused, not generic",
        requirements=["offer", "landing-page", "lead-capture", "analytics-ready", "browser-qa"],
    )
    target = revenue_ops.set_target(
        root,
        f"{clean_title} first revenue target",
        target_revenue=target_revenue,
        cadence=cadence,
    )
    brief = office_layer.create_markdown_brief(
        root,
        f"{clean_title} Launch Brief",
        {
            "Request": clean_request,
            "Offer": "Define the first offer, price hypothesis, guarantee, and proof plan before outreach.",
            "Acquisition": "Pick one primary channel, one backup channel, and log visits, leads, replies, and conversions.",
            "Operations": "Track fulfillment, support, blockers, expenses, revenue, and next actions each review.",
            "Approval Gates": "\n".join(f"- {gate}" for gate in approval_gates()),
        },
        folder="business",
        purpose="business launch autopilot brief",
    )
    launch = BusinessLaunch(
        launch_id="biz_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        title=clean_title,
        request=clean_request,
        goal_id=goal.goal_id,
        thread_id=thread.thread_id,
        pipeline_id=pipeline.pipeline_id,
        revenue_target_id=target.target_id,
        office_artifact_id=brief.office_id,
        approval_gates=approval_gates(),
        stages=default_stages(brief.rel_path),
        created_at=_now(),
        updated_at=_now(),
    )
    rows = [item for item in list_launches(root, include_all=True) if item.title.lower() != launch.title.lower()]
    rows.insert(0, launch)
    _write(root, rows)
    work_threads.update_thread(
        thread.thread_id,
        artifacts=[brief.rel_path],
        last_note=f"business launch autopilot started: {clean_title}",
        source="business-launch",
    )
    return launch


def update_stage(cwd: str | Path, launch_id: str, stage_key: str, *, status: str, artifact: str = "") -> BusinessLaunch:
    root = Path(cwd).expanduser().resolve()
    rows = []
    updated: BusinessLaunch | None = None
    for launch in list_launches(root, include_all=True):
        if launch.launch_id != launch_id:
            rows.append(launch)
            continue
        stages = [
            replace(stage, status=_stage_status(status), artifact=artifact or stage.artifact)
            if stage.key == stage_key
            else stage
            for stage in launch.stages
        ]
        updated = replace(launch, stages=stages, updated_at=_now())
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown business launch: {launch_id}")
    _write(root, rows)
    return updated


def list_launches(cwd: str | Path, *, include_all: bool = False, limit: int = 50) -> list[BusinessLaunch]:
    rows = _read(cwd)
    if not include_all:
        rows = [row for row in rows if row.status in {"active", "blocked"}]
    rows.sort(key=lambda row: row.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_launches(cwd, include_all=True, limit=20)
    return {
        "total": len(rows),
        "active": sum(1 for row in rows if row.status == "active"),
        "approvalGated": sum(1 for row in rows for stage in row.stages if stage.approval_required),
        "launches": [row.to_dict() for row in rows[:8]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 4) -> str:
    rows = list_launches(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Business Launch Autopilot"]
    for row in rows:
        next_stage = next((stage for stage in row.stages if stage.status != "done"), row.stages[-1])
        lines.append(
            f"- {row.title}: status={row.status}; next={next_stage.title}; pipeline={row.pipeline_id}; revenue_target={row.revenue_target_id}; approvals={len(row.approval_gates)}"
        )
    return "\n".join(lines)


def approval_gates() -> list[str]:
    return [
        "Create or log into external accounts only after explicit approval.",
        "Do not spend money, buy domains, subscribe to tools, or set up payment processors without approval.",
        "Draft posts, emails, DMs, ads, and listings locally first; send/publish only after approval.",
        "Track revenue and expenses locally; never store raw payment credentials.",
    ]


def default_stages(brief_path: str = "") -> list[LaunchStage]:
    return [
        LaunchStage("thesis", "Business thesis", "ready", artifact=brief_path),
        LaunchStage("offer", "Offer and pricing"),
        LaunchStage("site", "Landing page and lead capture"),
        LaunchStage("content", "Content and outreach drafts", approval_required=True),
        LaunchStage("analytics", "Analytics and revenue tracking"),
        LaunchStage("payment", "Payment path draft", approval_required=True),
        LaunchStage("launch", "External launch actions", approval_required=True),
        LaunchStage("operate", "Operations cadence"),
    ]


def _read(cwd: str | Path) -> list[BusinessLaunch]:
    path = launches_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("launches", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(_launch_from_dict(item))
        except Exception:
            continue
    return [row for row in rows if row.launch_id and row.cwd]


def _write(cwd: str | Path, rows: list[BusinessLaunch]) -> None:
    path = launches_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "launches": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _launch_from_dict(item: dict[str, Any]) -> BusinessLaunch:
    stages = [
        LaunchStage(
            key=str(raw.get("key") or ""),
            title=str(raw.get("title") or ""),
            status=_stage_status(str(raw.get("status") or "pending")),
            owner=str(raw.get("owner") or "Crypt"),
            approval_required=bool(raw.get("approval_required")),
            artifact=str(raw.get("artifact") or ""),
        )
        for raw in item.get("stages", [])
        if isinstance(raw, dict)
    ]
    return BusinessLaunch(
        launch_id=str(item.get("launch_id") or ""),
        cwd=str(item.get("cwd") or ""),
        title=str(item.get("title") or ""),
        request=str(item.get("request") or ""),
        goal_id=str(item.get("goal_id") or ""),
        thread_id=str(item.get("thread_id") or ""),
        pipeline_id=str(item.get("pipeline_id") or ""),
        revenue_target_id=str(item.get("revenue_target_id") or ""),
        office_artifact_id=str(item.get("office_artifact_id") or ""),
        approval_gates=[str(value) for value in item.get("approval_gates", []) if str(value).strip()],
        stages=stages or default_stages(),
        status=str(item.get("status") or "active"),
        created_at=int(item.get("created_at") or 0),
        updated_at=int(item.get("updated_at") or 0),
    )


def _title_from_request(request: str) -> str:
    clean = _clean(request, 90)
    for prefix in ("start a", "start", "build a", "build", "create a", "create"):
        if clean.lower().startswith(prefix):
            clean = clean[len(prefix):].strip(" :-")
            break
    return clean[:1].upper() + clean[1:] if clean else "Business Launch"


def _looks_like_launch_request(text: str) -> bool:
    lower = str(text or "").lower()
    if not business_mission.is_business_text(lower):
        return False
    return any(term in lower for term in ("start", "build", "create", "launch", "sell", "make money", "income"))


def _stage_status(value: str) -> str:
    clean = str(value or "pending").strip().lower()
    return clean if clean in {"pending", "ready", "running", "done", "blocked", "failed"} else "pending"


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
