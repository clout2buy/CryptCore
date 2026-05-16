"""Autonomous user-facing documentation writer."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import session, settings


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DocSection:
    title: str
    body: str
    bullets: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"## {self.title}", "", self.body.strip()]
        if self.bullets:
            lines.append("")
            lines.extend(f"- {bullet.strip()}" for bullet in self.bullets if bullet.strip())
        return "\n".join(lines).strip()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentationBuild:
    build_id: str
    path: str
    section_count: int
    capability_count: int
    word_count: int
    updated_at: int
    sections: list[DocSection] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "sections": [section.to_dict() for section in self.sections],
        }


def docs_dir(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "docs"


def guide_path(cwd: str | Path) -> Path:
    return docs_dir(cwd) / "crypt_user_guide.md"


def manifest_path(cwd: str | Path) -> Path:
    return docs_dir(cwd) / "autonomous_docs.json"


def write_guide(cwd: str | Path, runtime: dict[str, Any] | None = None) -> DocumentationBuild:
    root = Path(cwd).expanduser().resolve()
    sections = build_sections(runtime or {})
    markdown = _markdown(sections, runtime or {})
    path = guide_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    settings.restrict_file_permissions(path)
    build = DocumentationBuild(
        build_id=f"docs_{int(time.time())}",
        path=str(path),
        section_count=len(sections),
        capability_count=_capability_count(runtime or {}),
        word_count=len(markdown.split()),
        updated_at=int(time.time()),
        sections=sections,
    )
    manifest_path(root).write_text(json.dumps({"schema": SCHEMA_VERSION, "build": build.to_dict()}, indent=2), encoding="utf-8")
    settings.restrict_file_permissions(manifest_path(root))
    return build


def snapshot(cwd: str | Path, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    build = _read(cwd)
    runtime_count = _capability_count(runtime or {})
    if build is None or build.capability_count != runtime_count:
        build = write_guide(cwd, runtime or {})
    return {
        "schema": SCHEMA_VERSION,
        "path": build.path,
        "sectionCount": build.section_count,
        "capabilityCount": build.capability_count,
        "wordCount": build.word_count,
        "updatedAt": build.updated_at,
        "sections": [section.to_dict() for section in build.sections[:8]],
    }


def build_sections(runtime: dict[str, Any]) -> list[DocSection]:
    features = _feature_labels(runtime)
    ready = _ready_capabilities(runtime)
    return [
        DocSection(
            "Talk To Crypt",
            "Use normal language. Crypt decides whether a message is casual chat, mission work, file work, research, memory, voice, or a tool run.",
            [
                "Say what outcome you want instead of choosing a workflow.",
                "Crypt can create missions and follow-up threads when a request needs more than one step.",
                "Use the chat as the main control surface; Settings is for inspection, not orchestration.",
            ],
        ),
        DocSection(
            "Autonomous Missions",
            "Longer requests become tracked missions with next actions, blockers, budgets, workers, receipts, and approval gates.",
            _bullets_from_features(features, ("Missions", "Mission Workers", "Mission Budget", "Persistent Jobs")),
        ),
        DocSection(
            "Memory And Learning",
            "Crypt passively stores useful long-term preferences, project facts, visual notes, voice preferences, and tool recovery lessons while filtering weak noise.",
            _bullets_from_features(features, ("Memory", "Screenshot Memory", "Tool Failure Memory", "Knowledge Packs", "Persona")),
        ),
        DocSection(
            "Voice",
            "Local voice mode supports speech input, local Kokoro speech output, wake-session tracking, interruptions, confirmations, and voice preferences.",
            [
                "Use the mic button to dictate; interim speech is flushed before sending.",
                "When voice output is on, Crypt skips emojis, code blocks, links, and noisy tool output before speaking.",
                "Wake phrases and interruptions are saved as runtime state so voice behaves more naturally over time.",
            ],
        ),
        DocSection(
            "Files And Artifacts",
            "Generated sites, documents, screenshots, knowledge packs, and reusable assets are indexed with source, purpose, and mission links.",
            _bullets_from_features(features, ("Files", "Asset Library", "Artifact Studio", "Workspace Map", "Site pipelines")),
        ),
        DocSection(
            "External Actions",
            "Anything that posts, sends, pays, logs into accounts, or changes external systems stays approval-gated and leaves receipts.",
            _bullets_from_features(features, ("External Draft Queue", "External Receipts", "Credential Vault", "Connector Readiness", "Approval Policy")),
        ),
        DocSection(
            "Runtime Health",
            "Crypt watches its own live events, cache, provider health, accessibility, safety, and release-readiness checks.",
            _bullets_from_features(features, ("Live Event Integrity", "WebUI Cache", "Provider Health", "Accessibility Motion Audit", "Repair Doctor", "Chaos Checks")),
        ),
        DocSection(
            "Current Readiness",
            "This guide is rebuilt from the local runtime so it stays aligned with what is actually available.",
            ready[:8] or ["No capability matrix has been reported yet."],
        ),
    ]


def prompt_section(cwd: str | Path) -> str:
    build = _read(cwd)
    if build is None:
        return ""
    return (
        "# Autonomous Documentation Writer\n"
        f"- User guide: {build.path}; sections={build.section_count}; words={build.word_count}\n"
        "- Keep user-facing explanations aligned with this guide and avoid internal implementation noise unless asked."
    )


def _markdown(sections: list[DocSection], runtime: dict[str, Any]) -> str:
    lines = [
        "# Crypt User Guide",
        "",
        "This guide is generated from Crypt's local runtime. It explains what to use, not how the internals are wired.",
        "",
        f"Last rebuilt: {_timestamp()}",
        f"Runtime capabilities detected: {_capability_count(runtime)}",
        "",
    ]
    lines.extend("\n\n".join(section.to_markdown() for section in sections).splitlines())
    lines.append("")
    return "\n".join(lines)


def _read(cwd: str | Path) -> DocumentationBuild | None:
    path = manifest_path(cwd)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return None
    item = data.get("build") or {}
    if not isinstance(item, dict):
        return None
    try:
        return DocumentationBuild(
            build_id=str(item.get("build_id") or ""),
            path=str(item.get("path") or ""),
            section_count=int(item.get("section_count") or 0),
            capability_count=int(item.get("capability_count") or 0),
            word_count=int(item.get("word_count") or 0),
            updated_at=int(item.get("updated_at") or 0),
            sections=[
                DocSection(
                    title=str(raw.get("title") or ""),
                    body=str(raw.get("body") or ""),
                    bullets=[str(value) for value in raw.get("bullets", []) if str(value).strip()],
                )
                for raw in item.get("sections", [])
                if isinstance(raw, dict)
            ],
        )
    except Exception:
        return None


def _feature_labels(runtime: dict[str, Any]) -> set[str]:
    labels = set()
    features = runtime.get("coreFeatures", [])
    feature_rows = features if isinstance(features, list) else []
    for feature in feature_rows:
        if isinstance(feature, dict) and feature.get("label"):
            labels.add(str(feature["label"]))
    labels.update(
        str(card.get("label"))
        for card in runtime.get("capabilityMatrix", {}).get("capabilities", [])
        if isinstance(card, dict) and card.get("label")
    )
    return labels


def _ready_capabilities(runtime: dict[str, Any]) -> list[str]:
    rows = runtime.get("capabilityMatrix", {}).get("capabilities", [])
    out = []
    capability_rows = rows if isinstance(rows, list) else []
    for row in capability_rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or row.get("id") or "Capability")
        status = str(row.get("status") or "unknown")
        out.append(f"{label}: {status}")
    return out


def _bullets_from_features(features: set[str], names: tuple[str, ...]) -> list[str]:
    bullets = [f"{name} is available in the local runtime." for name in names if name in features]
    return bullets or [f"{names[0]} support is documented when the runtime reports it ready."]


def _capability_count(runtime: dict[str, Any]) -> int:
    matrix = runtime.get("capabilityMatrix", {})
    if isinstance(matrix, dict) and int(matrix.get("total") or 0):
        return int(matrix.get("total") or 0)
    features = runtime.get("coreFeatures", [])
    return len(features) if isinstance(features, list) else 0


def _timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
