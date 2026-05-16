"""Expanded autonomous-agent evaluation harness metadata and scoring."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import session, settings


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class EvalScenario:
    scenario_id: str
    category: str
    title: str
    goal: str
    evidence_keys: list[str] = field(default_factory=list)
    rubric: list[str] = field(default_factory=list)
    cadence: str = "nightly"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalScore:
    scenario_id: str
    category: str
    title: str
    score: float
    status: str
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SCENARIOS = [
    EvalScenario(
        "business_autopilot",
        "business",
        "Business Autopilot",
        "Create launch/revenue/content state with approval gates and next actions.",
        ["businessLaunch", "businessEntities", "revenueOps", "contentOps", "externalDrafts"],
        ["offer or launch exists", "revenue target or forecast exists", "external drafts are approval-gated"],
    ),
    EvalScenario(
        "research_source_quality",
        "research",
        "Research Source Quality",
        "Save reusable sources with URLs, summaries, trust notes, and prompt recall.",
        ["researchSources", "dataImports", "localSearch"],
        ["source count", "indexed context", "imported evidence"],
    ),
    EvalScenario(
        "memory_self_improvement",
        "memory",
        "Memory Self-Improvement",
        "Promote durable preferences, open loops, and persona context without manual orchestration.",
        ["memoryJournal", "personaGovernance", "skillOutcomeAutoforge"],
        ["long-term memory", "open loops", "persona governance"],
    ),
    EvalScenario(
        "browser_visual_qa",
        "browser",
        "Browser Visual QA",
        "Record browser activity, screenshots, console errors, and release screenshot targets.",
        ["browserRecordings", "releaseScreenshots", "artifactGraph"],
        ["recording count", "screenshot coverage", "artifact links"],
    ),
    EvalScenario(
        "voice_conversation",
        "voice",
        "Voice Conversation",
        "Support local voice output, transcript memory, interruptions, and short-response mode.",
        ["voice", "voiceConversation", "memoryJournal"],
        ["voice readiness", "turn count", "interruption tracking"],
    ),
    EvalScenario(
        "webui_stability",
        "webui",
        "WebUI Stability",
        "Keep chat live updates stable while surfacing jobs, approvals, mobile state, and notifications.",
        ["liveReplay", "jobQueue", "notifications", "mobileCompanion", "safetyIncidents"],
        ["live replay", "job persistence", "mobile companion", "incident visibility"],
    ),
]


def reports_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "eval-harness" / "latest-report.json"


def snapshot(cwd: str | Path, data: dict[str, Any] | None = None) -> dict[str, Any]:
    report = score_snapshot(cwd, data)
    return {
        "schema": SCHEMA_VERSION,
        "total": len(SCENARIOS),
        "passing": sum(1 for item in report["scores"] if item["status"] == "pass"),
        "watch": sum(1 for item in report["scores"] if item["status"] == "watch"),
        "failing": sum(1 for item in report["scores"] if item["status"] == "fail"),
        "overallScore": report["overallScore"],
        "categories": _counts(scenario.category for scenario in SCENARIOS),
        "scenarios": [scenario.to_dict() for scenario in SCENARIOS],
        "scores": report["scores"],
    }


def score_snapshot(cwd: str | Path, data: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(cwd).expanduser().resolve()
    state = data or _collect_snapshot(root)
    scores = [_score_scenario(scenario, state) for scenario in SCENARIOS]
    overall = round(sum(item.score for item in scores) / max(1, len(scores)), 3)
    return {
        "cwd": str(root),
        "generatedAt": _now(),
        "overallScore": overall,
        "scores": [item.to_dict() for item in scores],
    }


def write_report(cwd: str | Path, data: dict[str, Any] | None = None) -> dict[str, Any]:
    report = score_snapshot(cwd, data)
    path = reports_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": SCHEMA_VERSION, "report": report}, indent=2), encoding="utf-8")
    settings.restrict_file_permissions(path)
    return report


def prompt_section(cwd: str | Path, data: dict[str, Any] | None = None, *, limit: int = 6) -> str:
    snap = snapshot(cwd, data)
    lines = ["# Evaluation Harness Expansion", f"- overall={snap['overallScore']:.2f}; passing={snap['passing']}/{snap['total']}"]
    for score in snap["scores"][:limit]:
        lines.append(f"- {score['status']} {score['category']}: {score['title']} score={score['score']:.2f}")
    return "\n".join(lines)


def _score_scenario(scenario: EvalScenario, state: dict[str, Any]) -> EvalScore:
    evidence = []
    missing = []
    for key in scenario.evidence_keys:
        score = _evidence_score(key, state.get(key))
        if score > 0:
            evidence.append(f"{key}:{score:.2f}")
        else:
            missing.append(key)
    score_value = round(sum(_evidence_score(key, state.get(key)) for key in scenario.evidence_keys) / max(1, len(scenario.evidence_keys)), 3)
    status = "pass" if score_value >= 0.66 else ("watch" if score_value >= 0.33 else "fail")
    return EvalScore(
        scenario_id=scenario.scenario_id,
        category=scenario.category,
        title=scenario.title,
        score=score_value,
        status=status,
        evidence=evidence,
        missing=missing,
    )


def _evidence_score(key: str, value: Any) -> float:
    if not value:
        return 0.0
    if isinstance(value, dict):
        if key == "voice":
            return 1.0 if value.get("ready") else 0.35
        if key == "voiceConversation":
            return min(1.0, (int(value.get("turnCount") or 0) + int(value.get("interruptionCount") or 0)) / 3)
        if key == "memoryJournal":
            return min(1.0, (int(value.get("longTermCount") or 0) + int(value.get("openLoopCount") or 0)) / 6)
        if key == "researchSources":
            return min(1.0, int(value.get("total") or 0) / 3)
        if key == "browserRecordings":
            return min(1.0, int(value.get("total") or 0) / 2)
        if key == "jobQueue":
            return 1.0 if any(int(value.get(name) or 0) for name in ("queued", "running", "completed", "failed", "interrupted")) else 0.25
        if key in {"mobileCompanion", "personaGovernance", "approvalPolicy", "safetyIncidents"}:
            return 0.8 if value else 0.0
        for field_name in ("total", "count", "active", "ready", "documents", "nodes", "edges", "pieces", "targets", "open"):
            if _numeric(value.get(field_name)) > 0:
                return 1.0
        summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
        if any(_numeric(summary.get(name)) > 0 for name in ("nodes", "edges", "total", "artifacts", "missions")):
            return 1.0
        return 0.35
    if isinstance(value, list):
        return min(1.0, len(value) / 3)
    return 0.2


def _collect_snapshot(root: Path) -> dict[str, Any]:
    from . import (
        artifact_graph,
        browser_recorder,
        business_entities,
        business_launch,
        content_ops,
        data_importer,
        external_drafts,
        job_queue,
        local_search_index,
        local_voice,
        memory_journal,
        mobile_companion,
        notification_center,
        persona_governance,
        research_sources,
        safety_incidents,
        skill_outcome_autoforge,
        voice_conversation,
    )

    base: dict[str, Any] = {
        "businessLaunch": business_launch.snapshot(root),
        "businessEntities": business_entities.snapshot(root),
        "contentOps": content_ops.snapshot(root),
        "externalDrafts": external_drafts.snapshot(root),
        "researchSources": research_sources.snapshot(root),
        "dataImports": data_importer.snapshot(root),
        "localSearch": local_search_index.snapshot(root),
        "memoryJournal": memory_journal.snapshot(root),
        "personaGovernance": persona_governance.audit(root),
        "skillOutcomeAutoforge": skill_outcome_autoforge.snapshot(root),
        "browserRecordings": browser_recorder.snapshot(root),
        "artifactGraph": artifact_graph.build(root),
        "voice": local_voice.status().to_dict(),
        "voiceConversation": voice_conversation.snapshot(root),
        "liveReplay": {},
        "jobQueue": job_queue.snapshot(root),
        "notifications": notification_center.snapshot(root),
        "safetyIncidents": safety_incidents.snapshot(root),
    }
    base["mobileCompanion"] = mobile_companion.snapshot(root, {"personalOS": {}, **base})
    return base


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _numeric(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


def _now() -> int:
    return int(time.time())
