"""Workspace map with safe edit zones, generated areas, and ignored paths."""
from __future__ import annotations

import fnmatch
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import session


SOURCE_ZONES = {
    "core": ("runtime source", "Edit with focused tests and py_compile."),
    "tests": ("test suite", "Add or update tests beside runtime changes."),
    "docs": ("documentation", "Safe for plans, notes, release docs, and user-facing docs."),
    "scripts": ("automation scripts", "Edit with shell syntax or focused smoke checks."),
    "tools": ("developer tools", "Edit with focused command checks."),
    "benchmarks": ("evaluation tasks", "Edit only when benchmark coverage changes."),
    ".agents/skills": ("project skills", "Safe for project-local skill instructions."),
}
GENERATED_NAMES = {
    ".crypt",
    "office",
    "release",
    "dist",
    "build",
    "logs",
    "runs",
    "tasks",
    "bench-runs",
    "target-evals",
    "traces",
    "No Mans Sky Navigator",
}
FORBIDDEN_NAMES = {
    ".git",
    ".env",
    ".env.local",
    "auth.json",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}


@dataclass(frozen=True)
class WorkspaceEntry:
    name: str
    rel_path: str
    path: str
    kind: str
    role: str
    safe_to_edit: bool
    generated: bool = False
    ignored: bool = False
    reason: str = ""
    size: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build(cwd: str | Path, *, limit: int = 120) -> dict[str, Any]:
    root = Path(cwd).expanduser().resolve()
    ignored_patterns = ignore_patterns(root)
    top_level = _top_level(root, ignored_patterns, limit=limit)
    safe_zones = _safe_zones(root)
    generated_zones = _generated_zones(root, ignored_patterns)
    risky_zones = [entry for entry in top_level if not entry.safe_to_edit and (entry.ignored or entry.name in FORBIDDEN_NAMES)]
    project_store = session.project_dir(root)
    return {
        "root": str(root),
        "projectStore": str(project_store),
        "generatedAt": _now(),
        "summary": {
            "topLevel": len(top_level),
            "safeZones": len([zone for zone in safe_zones if zone["exists"]]),
            "generatedZones": len([zone for zone in generated_zones if zone["exists"]]),
            "ignoredPatterns": len(ignored_patterns),
            "riskyZones": len(risky_zones),
        },
        "safeZones": safe_zones,
        "generatedZones": generated_zones,
        "ignoredPatterns": ignored_patterns[:80],
        "riskyZones": [entry.to_dict() for entry in risky_zones[:20]],
        "topLevel": [entry.to_dict() for entry in top_level],
    }


def snapshot(cwd: str | Path) -> dict[str, Any]:
    return build(cwd, limit=80)


def prompt_section(cwd: str | Path, *, limit: int = 8) -> str:
    data = build(cwd, limit=60)
    safe = [zone["relPath"] for zone in data["safeZones"] if zone["exists"]][:limit]
    generated = [zone["relPath"] for zone in data["generatedZones"] if zone["exists"]][:limit]
    risky = [zone["rel_path"] for zone in data["riskyZones"]][:limit]
    lines = ["# Workspace Map", f"- root={data['root']}"]
    if safe:
        lines.append(f"- safe edit zones: {', '.join(safe)}")
    if generated:
        lines.append(f"- generated/local-only zones: {', '.join(generated)}")
    if risky:
        lines.append(f"- avoid editing or committing: {', '.join(risky)}")
    lines.append("- Before file edits, prefer the smallest safe zone that matches the task and verify with focused checks.")
    return "\n".join(lines)


def ignore_patterns(cwd: str | Path) -> list[str]:
    root = Path(cwd).expanduser().resolve()
    path = root / ".gitignore"
    patterns: list[str] = []
    if path.exists():
        try:
            for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith("!"):
                    continue
                patterns.append(line)
        except OSError:
            pass
    for name in sorted(FORBIDDEN_NAMES | GENERATED_NAMES):
        pattern = f"{name}/" if "." not in Path(name).suffix and not name.startswith(".env") else name
        if pattern not in patterns:
            patterns.append(pattern)
    return _dedupe(patterns)


def _top_level(root: Path, ignored_patterns: list[str], *, limit: int) -> list[WorkspaceEntry]:
    try:
        entries = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError:
        return []
    out: list[WorkspaceEntry] = []
    for item in entries:
        rel = item.name
        role, reason, safe = _role(rel, item)
        ignored = _ignored(rel, ignored_patterns) or item.name in FORBIDDEN_NAMES
        generated = _generated(rel, item)
        if ignored and item.name not in {".crypt", ".agents", ".github"} and not _safe_source(rel):
            safe = False
            if not role:
                role = "ignored/local"
            if not reason:
                reason = "Ignored by workspace policy or gitignore."
        try:
            stat = item.stat()
        except OSError:
            continue
        out.append(
            WorkspaceEntry(
                name=item.name,
                rel_path=rel,
                path=str(item),
                kind="dir" if item.is_dir() else "file",
                role=role or ("generated artifact" if generated else "workspace item"),
                safe_to_edit=bool(safe and not ignored),
                generated=generated,
                ignored=ignored,
                reason=reason or ("Generated output; edit only when the user asks." if generated else "Top-level workspace item."),
                size=stat.st_size if item.is_file() else 0,
                updated_at=int(stat.st_mtime),
            )
        )
        if len(out) >= limit:
            break
    return out


def _safe_zones(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rel, (role, reason) in SOURCE_ZONES.items():
        path = root / rel
        out.append(
            {
                "relPath": rel,
                "path": str(path),
                "role": role,
                "reason": reason,
                "exists": path.exists(),
            }
        )
    return out


def _generated_zones(root: Path, ignored_patterns: list[str]) -> list[dict[str, Any]]:
    names = sorted(GENERATED_NAMES | {".crypt", root.joinpath("office").name})
    out = []
    for name in names:
        path = root / name
        out.append(
            {
                "relPath": name,
                "path": str(path),
                "role": "generated/local-only",
                "reason": "Treat as output or local state unless the task explicitly targets it.",
                "exists": path.exists(),
                "ignored": _ignored(name, ignored_patterns) or name in FORBIDDEN_NAMES,
            }
        )
    project_store = session.project_dir(root)
    out.append(
        {
            "relPath": "<crypt-project-store>",
            "path": str(project_store),
            "role": "durable agent state",
            "reason": "Crypt's per-project memory/session store; inspect intentionally and do not commit.",
            "exists": project_store.exists(),
            "ignored": True,
        }
    )
    return out


def _role(rel: str, path: Path) -> tuple[str, str, bool]:
    if rel in SOURCE_ZONES:
        role, reason = SOURCE_ZONES[rel]
        return role, reason, True
    if rel == ".agents":
        return "agent configuration", "Project skills and local agent instructions live under .agents/skills.", True
    if rel == ".github":
        return "repository automation", "CI and GitHub metadata; edit with focused workflow checks.", True
    if rel in FORBIDDEN_NAMES:
        return "protected/local", "Secrets, dependency folders, caches, or VCS state should not be edited casually.", False
    if _generated(rel, path):
        return "generated/local-only", "Generated output or local runtime state.", False
    if path.suffix.lower() in {".md", ".txt"}:
        return "workspace document", "Top-level docs are safe when the task targets documentation.", True
    if rel in {"README.md", "CONTRIBUTING.md", "SECURITY.md", "pyproject.toml", "requirements.txt", "requirements-dev.txt"}:
        return "project metadata", "Edit with matching tests or documentation checks.", True
    return "", "", path.is_file() and not rel.startswith(".")


def _safe_source(rel: str) -> bool:
    return rel in SOURCE_ZONES or rel in {".agents", ".github"}


def _generated(rel: str, path: Path) -> bool:
    if rel in GENERATED_NAMES:
        return True
    lowered = rel.lower()
    if lowered.endswith((".log", ".jsonl")):
        return True
    if path.is_dir() and lowered in {"dist", "build", "release", "logs", "runs"}:
        return True
    return False


def _ignored(rel: str, patterns: list[str]) -> bool:
    normalized = rel.replace("\\", "/")
    for pattern in patterns:
        pat = pattern.strip().replace("\\", "/")
        if not pat:
            continue
        if pat.endswith("/") and (normalized == pat[:-1] or normalized.startswith(pat)):
            return True
        if "/" not in pat and fnmatch.fnmatch(Path(normalized).name, pat):
            return True
        if fnmatch.fnmatch(normalized, pat) or fnmatch.fnmatch(normalized, pat.lstrip("/")):
            return True
    return False


def _dedupe(values: list[str]) -> list[str]:
    out = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _now() -> int:
    return int(time.time())
