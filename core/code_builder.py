"""Standard code-work loop for Crypt.

This module turns vague coding requests into a consistent operating contract:
inspect, plan, patch, test, review, summarize, then leave the work commit-ready.
It is deterministic so tests, WebUI hints, and future agents can share the same
stage language without exposing workflow controls to the user.
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import project_index, redact


STAGE_ORDER = ("inspect", "plan", "patch", "test", "review", "summarize", "commit-ready")
CODE_REQUEST_RE = re.compile(
    r"\b(code|repo|bug|fix|implement|refactor|test|tests|lint|build|"
    r"frontend|backend|api|script|module|class|function|component|ui)\b|"
    r"\.(py|js|ts|tsx|jsx|css|html|md|json|toml|yml|yaml)\b",
    re.I,
)
PATH_RE = re.compile(
    r"(?P<path>(?:[\w.-]+[\\/])+[\w.-]+\.(?:py|js|ts|tsx|jsx|css|html|md|json|toml|yml|yaml))"
    r"|(?P<file>\b[\w.-]+\.(?:py|js|ts|tsx|jsx|css|html|md|json|toml|yml|yaml)\b)",
    re.I,
)


@dataclass(frozen=True)
class CodeStage:
    name: str
    purpose: str
    status: str = "pending"
    command: str = ""
    evidence: str = ""


@dataclass(frozen=True)
class CodeBuildPlan:
    workspace: str
    request: str
    risk: str
    stages: list[CodeStage] = field(default_factory=list)
    primary_files: list[str] = field(default_factory=list)
    check_commands: list[str] = field(default_factory=list)
    created_at: int = 0


@dataclass(frozen=True)
class CodeBuildReport:
    workspace: str
    changed_files: list[str]
    check_commands: list[str]
    checks_passed: int
    checks_failed: int
    ready: bool
    next_stage: str
    diff_summary: str = ""


def is_code_request(text: str) -> bool:
    return bool(CODE_REQUEST_RE.search(str(text or "")))


def plan_task(cwd: str | Path, request: str) -> CodeBuildPlan:
    root = Path(cwd).expanduser().resolve()
    profile = project_index.get(root)
    checks = _check_commands(root, profile)
    primary_files = _primary_files(root, request, profile)
    risk = _risk(request, primary_files)
    stages = [
        CodeStage("inspect", "Read the files and local instructions before editing.", command=_inspect_command(primary_files)),
        CodeStage("plan", "Decide the smallest coherent patch and test scope."),
        CodeStage("patch", "Apply scoped edits with file tools; avoid unrelated churn."),
        CodeStage("test", "Run the nearest meaningful verification.", command=checks[0] if checks else ""),
        CodeStage("review", "Inspect the diff for regressions, security issues, and missing tests.", command="git diff --check"),
        CodeStage("summarize", "Report what changed, what passed, and remaining risk."),
        CodeStage("commit-ready", "Leave the work staged only when explicitly asked.", command="git status --short"),
    ]
    return CodeBuildPlan(
        workspace=str(root),
        request=redact.text(request),
        risk=risk,
        stages=stages,
        primary_files=primary_files,
        check_commands=checks,
        created_at=int(time.time()),
    )


def report_change(
    cwd: str | Path,
    *,
    changed_files: list[str],
    checks: list[dict[str, Any]] | None = None,
) -> CodeBuildReport:
    root = Path(cwd).expanduser().resolve()
    clean_files = _dedupe([str(item).strip() for item in changed_files if str(item).strip()])
    check_rows = checks or []
    passed = sum(1 for item in check_rows if bool(item.get("ok")))
    failed = sum(1 for item in check_rows if item and not bool(item.get("ok")))
    ready = bool(clean_files) and failed == 0 and (passed > 0 or not check_rows)
    next_stage = "commit-ready" if ready else ("test" if clean_files else "patch")
    return CodeBuildReport(
        workspace=str(root),
        changed_files=clean_files,
        check_commands=[str(item.get("command") or "") for item in check_rows if item.get("command")],
        checks_passed=passed,
        checks_failed=failed,
        ready=ready,
        next_stage=next_stage,
        diff_summary=_diff_summary(root, clean_files),
    )


def prompt_section(cwd: str | Path, request: str, *, limit: int = 4) -> str:
    if not is_code_request(request):
        return ""
    plan = plan_task(cwd, request)
    stage_text = " -> ".join(STAGE_ORDER)
    lines = [
        "# Code Builder Loop",
        f"- Stages: {stage_text}.",
        f"- Risk: {plan.risk}.",
        "- Rule: inspect the target files before patching, then run the closest useful check before completion.",
    ]
    if plan.primary_files:
        lines.append("- Likely files: " + ", ".join(plan.primary_files[:limit]))
    if plan.check_commands:
        lines.append("- Likely checks: " + "; ".join(plan.check_commands[:limit]))
    return "\n".join(lines)


def to_dict(plan: CodeBuildPlan) -> dict[str, Any]:
    return asdict(plan)


def _check_commands(root: Path, profile: project_index.ProjectProfile) -> list[str]:
    checks = list(profile.test_commands)
    if not checks:
        if any(root.rglob("*.py")):
            checks.append("python -m compileall -q .")
        if (root / "tests").exists():
            checks.append("python -m pytest tests -q")
    if not checks:
        checks.append("git diff --check")
    return _dedupe(checks)


def _primary_files(root: Path, request: str, profile: project_index.ProjectProfile) -> list[str]:
    paths = []
    for match in PATH_RE.finditer(request or ""):
        raw = (match.group("path") or match.group("file") or "").strip(" .,'\"")
        if raw:
            paths.append(raw.replace("\\", "/"))
    for key in profile.key_files[:6]:
        if key not in paths:
            paths.append(key)
    if not paths:
        for name in ("src", "core", "app", "tests"):
            if (root / name).exists():
                paths.append(name)
    return _dedupe(paths)[:10]


def _risk(request: str, primary_files: list[str]) -> str:
    text = str(request or "").lower()
    if any(token in text for token in ("all", "entire", "architecture", "security", "auth", "payment", "database")):
        return "high"
    if len(primary_files) > 4 or any(token in text for token in ("refactor", "redesign", "api", "backend")):
        return "medium"
    return "low"


def _inspect_command(primary_files: list[str]) -> str:
    if primary_files:
        return "read/search " + ", ".join(primary_files[:4])
    return "rg --files"


def _diff_summary(root: Path, changed_files: list[str]) -> str:
    if not changed_files:
        return "No changed files recorded."
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "--stat", "--", *changed_files],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        result = None
    text = (result.stdout if result and result.returncode == 0 else "").strip()
    if text:
        return redact.text(text)
    label = "file" if len(changed_files) == 1 else "files"
    return f"{len(changed_files)} changed {label}: " + ", ".join(changed_files[:8])


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = str(item).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out
