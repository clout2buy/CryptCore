"""Classify patch risk by blast radius, security, UI, data, and tests."""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PatchRiskReport:
    changed_paths: list[str]
    risk: str
    blast_radius: str
    security: str = "low"
    ui: str = "low"
    data: str = "low"
    tests: str = "missing"
    reasons: list[str] = field(default_factory=list)
    recommended_checks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify(cwd: str | Path, changed_paths: list[str] | None = None) -> PatchRiskReport:
    root = Path(cwd).expanduser().resolve()
    paths = _dedupe(changed_paths or _git_changed_paths(root))
    if not paths:
        return PatchRiskReport(
            changed_paths=[],
            risk="low",
            blast_radius="low",
            security="low",
            ui="low",
            data="low",
            tests="none",
            reasons=["no changed paths detected"],
            recommended_checks=["git diff --check"],
        )
    reasons: list[str] = []
    security = _dimension(paths, ("auth", "oauth", "token", "secret", "credential", "permission", "policy"))
    ui = _dimension(paths, ("webui", "static", ".css", ".html", ".tsx", ".jsx", "frontend"))
    data = _dimension(paths, ("settings", "session", "memory", "db", "database", "json", "migration", "schema"))
    tests = "present" if any(_is_test(path) for path in paths) else "missing"
    blast_radius = _blast_radius(paths)
    for label, value in (("security", security), ("ui", ui), ("data", data)):
        if value != "low":
            reasons.append(f"{label} surface touched")
    if blast_radius != "low":
        reasons.append(f"{blast_radius} blast radius")
    if tests == "missing" and paths:
        reasons.append("no test file changed")
    risk = _overall([security, ui, data, blast_radius], tests)
    return PatchRiskReport(
        changed_paths=paths,
        risk=risk,
        blast_radius=blast_radius,
        security=security,
        ui=ui,
        data=data,
        tests=tests,
        reasons=reasons or ["no changed paths detected"],
        recommended_checks=_checks(paths, security=security, ui=ui, data=data),
    )


def snapshot(cwd: str | Path) -> dict[str, Any]:
    return classify(cwd).to_dict()


def prompt_section(cwd: str | Path) -> str:
    report = classify(cwd)
    if not report.changed_paths:
        return ""
    return (
        "# Patch Risk\n"
        f"- risk={report.risk}; blast={report.blast_radius}; security={report.security}; "
        f"ui={report.ui}; data={report.data}; tests={report.tests}\n"
        f"- checks: {'; '.join(report.recommended_checks[:5])}"
    )


def _git_changed_paths(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _dimension(paths: list[str], markers: tuple[str, ...]) -> str:
    hits = sum(1 for path in paths if any(marker in path.lower() for marker in markers))
    if hits >= 3:
        return "high"
    if hits:
        return "medium"
    return "low"


def _blast_radius(paths: list[str]) -> str:
    if len(paths) >= 12:
        return "high"
    top_dirs = {path.replace("\\", "/").split("/", 1)[0] for path in paths if path}
    if len(paths) >= 5 or len(top_dirs) >= 4:
        return "medium"
    return "low"


def _overall(dimensions: list[str], tests: str) -> str:
    if "high" in dimensions:
        return "high"
    if dimensions.count("medium") >= 2:
        return "high" if tests == "missing" else "medium"
    if "medium" in dimensions:
        return "medium"
    return "low" if tests == "present" or not dimensions else "medium"


def _checks(paths: list[str], *, security: str, ui: str, data: str) -> list[str]:
    checks = ["git diff --check"]
    if any(path.endswith(".py") for path in paths):
        checks.append("python -m py_compile " + " ".join(path for path in paths if path.endswith(".py"))[:180])
        checks.append("pytest")
    if ui != "low" or any(path.endswith(".js") for path in paths):
        checks.append("node --check core\\webui_static\\app.js")
    if security != "low":
        checks.append("review auth/secret handling before commit")
    if data != "low":
        checks.append("test persistence round trip")
    return _dedupe(checks)


def _is_test(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.startswith("tests/") or "/test_" in normalized or normalized.endswith(".test.js")


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(str(value or "").split())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out
