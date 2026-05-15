"""Repeatable website/app generation pipeline."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import artifact_studio, session, settings


SCHEMA_VERSION = 1
SITE_RE = re.compile(r"\b(website|web site|landing page|homepage|frontend|front-end|webui|web app|site|app)\b", re.I)


@dataclass(frozen=True)
class PipelineStage:
    key: str
    title: str
    status: str = "pending"
    output: str = ""
    checks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WebsitePipeline:
    pipeline_id: str
    cwd: str
    title: str
    prompt: str
    audience: str = ""
    aesthetic_direction: str = ""
    status: str = "active"
    requirements: list[str] = field(default_factory=list)
    stages: list[PipelineStage] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "stages": [asdict(stage) for stage in self.stages],
        }


@dataclass(frozen=True)
class PipelineDecision:
    pipeline: WebsitePipeline | None
    created: bool = False
    reason: str = ""


DEFAULT_STAGES = (
    PipelineStage("brief", "Brief", "ready", "Capture purpose, audience, constraints, and success metric."),
    PipelineStage("direction", "Design Direction", "pending", "Choose a bold aesthetic direction and UX shape."),
    PipelineStage("build", "Implementation", "pending", "Create working HTML/CSS/JS or app code."),
    PipelineStage("preview", "Preview", "pending", "Launch/open the local result for inspection."),
    PipelineStage("qa", "Visual QA", "pending", "Check desktop/mobile layout, console, assets, and motion."),
    PipelineStage("iterate", "Iteration", "pending", "Apply feedback and tighten details."),
    PipelineStage("release", "Release Notes", "pending", "Record files, checks, screenshots, and known risks."),
)


def pipelines_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "website_pipeline" / "pipelines.json"


def create_pipeline(
    cwd: str | Path,
    prompt: str,
    *,
    title: str = "",
    audience: str = "",
    aesthetic_direction: str = "",
    requirements: list[str] | None = None,
) -> WebsitePipeline:
    root = Path(cwd).expanduser().resolve()
    now = _now()
    clean_prompt = _clean(prompt, 2_000)
    clean_title = _clean(title, 120) or _title_from_prompt(clean_prompt)
    pipeline = WebsitePipeline(
        pipeline_id=_pipeline_id(root, clean_title),
        cwd=str(root),
        title=clean_title,
        prompt=clean_prompt,
        audience=_clean(audience, 180),
        aesthetic_direction=_clean(aesthetic_direction, 180) or "distinctive, production-grade, context-specific",
        requirements=_dedupe(requirements or _requirements_from_prompt(clean_prompt)),
        stages=list(DEFAULT_STAGES),
        created_at=now,
        updated_at=now,
    )
    rows = [item for item in list_pipelines(root, include_all=True) if item.pipeline_id != pipeline.pipeline_id]
    rows.insert(0, pipeline)
    _write(root, rows)
    _write_markdown(root, rows)
    return pipeline


def ensure_for_prompt(cwd: str | Path, prompt: str) -> PipelineDecision:
    if not is_site_request(prompt):
        return PipelineDecision(None, False, "not a website/app request")
    root = Path(cwd).expanduser().resolve()
    title = _title_from_prompt(prompt)
    existing = next((item for item in list_pipelines(root) if _norm(item.title) == _norm(title)), None)
    if existing:
        return PipelineDecision(existing, False, "matched existing website pipeline")
    return PipelineDecision(create_pipeline(root, prompt, title=title), True, "created website pipeline")


def update_stage(
    cwd: str | Path,
    pipeline_id: str,
    stage_key: str,
    *,
    status: str,
    output: str = "",
    checks: list[str] | None = None,
) -> WebsitePipeline:
    root = Path(cwd).expanduser().resolve()
    rows = []
    updated: WebsitePipeline | None = None
    now = _now()
    for pipeline in list_pipelines(root, include_all=True):
        if pipeline.pipeline_id != pipeline_id:
            rows.append(pipeline)
            continue
        stages = []
        for stage in pipeline.stages:
            if stage.key == stage_key:
                stages.append(
                    PipelineStage(
                        stage.key,
                        stage.title,
                        _stage_status(status),
                        _clean(output or stage.output, 800),
                        _dedupe(checks or stage.checks),
                    )
                )
            else:
                stages.append(stage)
        updated = replace(pipeline, stages=stages, updated_at=now)
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown website pipeline: {pipeline_id}")
    _write(root, rows)
    _write_markdown(root, rows)
    return updated


def attach_artifact(cwd: str | Path, pipeline_id: str, path: str | Path, *, note: str = "") -> WebsitePipeline:
    root = Path(cwd).expanduser().resolve()
    record = artifact_studio.record_artifact(
        root,
        path,
        kind="site",
        provenance=f"website pipeline {pipeline_id}",
        source="website-pipeline",
        note=note or "attached to website pipeline",
    )
    rows = []
    updated: WebsitePipeline | None = None
    now = _now()
    for pipeline in list_pipelines(root, include_all=True):
        if pipeline.pipeline_id != pipeline_id:
            rows.append(pipeline)
            continue
        artifacts = _dedupe([record.rel_path.replace("\\", "/"), *pipeline.artifacts])
        updated = replace(pipeline, artifacts=artifacts, updated_at=now)
        rows.append(updated)
    if updated is None:
        raise KeyError(f"unknown website pipeline: {pipeline_id}")
    _write(root, rows)
    _write_markdown(root, rows)
    return updated


def list_pipelines(cwd: str | Path, *, include_all: bool = False, limit: int = 50) -> list[WebsitePipeline]:
    rows = _read(cwd)
    if not include_all:
        rows = [item for item in rows if item.status in {"active", "blocked"}]
    rows.sort(key=lambda item: item.updated_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_pipelines(cwd, include_all=True, limit=30)
    return {
        "total": len(rows),
        "active": sum(1 for row in rows if row.status == "active"),
        "pipelines": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 4) -> str:
    rows = list_pipelines(cwd, limit=limit)
    if not rows:
        return ""
    lines = ["# Website Generator Pipeline"]
    for row in rows:
        next_stage = next((stage for stage in row.stages if stage.status != "done"), row.stages[-1])
        lines.append(
            f"- {row.title}: status={row.status}; next={next_stage.title}; direction={row.aesthetic_direction}; artifacts={', '.join(row.artifacts[:3]) or 'none yet'}"
        )
    return "\n".join(lines)


def is_site_request(text: str) -> bool:
    return bool(SITE_RE.search(str(text or "")))


def _read(cwd: str | Path) -> list[WebsitePipeline]:
    path = pipelines_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[WebsitePipeline] = []
    for item in data.get("pipelines", []):
        if not isinstance(item, dict):
            continue
        try:
            out.append(_pipeline_from_dict(item))
        except Exception:
            continue
    return out


def _write(cwd: str | Path, rows: list[WebsitePipeline]) -> None:
    path = pipelines_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "pipelines": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _write_markdown(cwd: str | Path, rows: list[WebsitePipeline]) -> None:
    path = pipelines_path(cwd).with_name("WEBSITE_PIPELINES.md")
    lines = ["# Website Pipelines", ""]
    if not rows:
        lines.append("No website pipelines yet.")
    for row in rows:
        lines.extend(["", f"## {row.title}", "", f"- **Status:** {row.status}", f"- **Direction:** {row.aesthetic_direction}"])
        if row.requirements:
            lines.append(f"- **Requirements:** {', '.join(row.requirements)}")
        if row.artifacts:
            lines.append(f"- **Artifacts:** {', '.join(row.artifacts)}")
        lines.append("")
        for stage in row.stages:
            lines.append(f"- [{stage.status}] {stage.title}: {stage.output}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    settings.restrict_file_permissions(path)


def _pipeline_from_dict(item: dict[str, Any]) -> WebsitePipeline:
    stages = []
    for raw in item.get("stages", []):
        if isinstance(raw, dict):
            stages.append(
                PipelineStage(
                    key=str(raw.get("key") or ""),
                    title=str(raw.get("title") or ""),
                    status=_stage_status(str(raw.get("status") or "pending")),
                    output=str(raw.get("output") or ""),
                    checks=[str(value) for value in raw.get("checks", []) if str(value).strip()],
                )
            )
    if not stages:
        stages = list(DEFAULT_STAGES)
    return WebsitePipeline(
        pipeline_id=str(item.get("pipeline_id") or ""),
        cwd=str(item.get("cwd") or ""),
        title=_clean(str(item.get("title") or "Website Pipeline"), 120),
        prompt=_clean(str(item.get("prompt") or ""), 2_000),
        audience=_clean(str(item.get("audience") or ""), 180),
        aesthetic_direction=_clean(str(item.get("aesthetic_direction") or ""), 180),
        status=str(item.get("status") or "active"),
        requirements=[str(value) for value in item.get("requirements", []) if str(value).strip()],
        stages=stages,
        artifacts=[str(value) for value in item.get("artifacts", []) if str(value).strip()],
        created_at=int(item.get("created_at") or 0),
        updated_at=int(item.get("updated_at") or 0),
    )


def _requirements_from_prompt(prompt: str) -> list[str]:
    lower = prompt.lower()
    requirements = []
    if "animation" in lower or "animated" in lower:
        requirements.append("motion")
    if "mobile" in lower or "responsive" in lower:
        requirements.append("responsive")
    if "business" in lower or "sell" in lower or "landing" in lower:
        requirements.append("conversion")
    if "dashboard" in lower or "tracker" in lower:
        requirements.append("data-surface")
    if "voice" in lower:
        requirements.append("voice-ui")
    return requirements or ["polished-ui", "browser-qa"]


def _title_from_prompt(prompt: str) -> str:
    clean = _clean(prompt, 80)
    clean = re.sub(r"^(build|make|create|design|ship)\s+(me\s+)?", "", clean, flags=re.I).strip()
    return clean[:1].upper() + clean[1:] if clean else "Website Pipeline"


def _pipeline_id(root: Path, title: str) -> str:
    digest = hashlib.sha1(f"{root}:{_norm(title)}".encode("utf-8")).hexdigest()[:12]
    return f"site_{digest}"


def _stage_status(value: str) -> str:
    clean = str(value or "pending").strip().lower()
    return clean if clean in {"pending", "ready", "running", "done", "blocked", "failed"} else "pending"


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value, 120)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _now() -> int:
    return int(time.time())
