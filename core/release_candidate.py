"""Crypt 1.0 release candidate manifest."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import chaos_checks, daily_brief, eval_harness, release_train, repair_doctor, session, settings


SCHEMA_VERSION = 1
VERSION = "1.0-rc"


@dataclass(frozen=True)
class ReleaseCandidate:
    rc_id: str
    version: str
    cwd: str
    status: str
    generated_at: int
    release_checklist: str
    chaos_report: str
    eval_report: str
    daily_brief: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    upgrade_notes: list[str] = field(default_factory=list)
    known_risks: list[str] = field(default_factory=list)
    rollback: list[str] = field(default_factory=list)
    push_package: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rc_dir(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "release" / "crypt-1.0"


def latest_path(cwd: str | Path) -> Path:
    return rc_dir(cwd) / "release-candidate.json"


def generate(
    cwd: str | Path,
    *,
    checks: list[str] | None = None,
    run_checks: bool = True,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(cwd).expanduser().resolve()
    output = Path(output_root).expanduser().resolve() if output_root else rc_dir(root)
    output.mkdir(parents=True, exist_ok=True)
    release = release_train.generate(root, checks=checks, output_root=output / "release-train", run_checks=run_checks)
    chaos = chaos_checks.write_report(root)
    eval_harness.write_report(root)
    brief = daily_brief.write_brief(root)
    repair = repair_doctor.snapshot(root)
    rc_dir(root).mkdir(parents=True, exist_ok=True)
    status = "pass" if release.success and chaos.get("status") == "pass" and not int(repair.get("critical") or 0) else "blocked"
    rc = ReleaseCandidate(
        rc_id="crypt-1.0-" + time.strftime("%Y%m%d-%H%M%S"),
        version=VERSION,
        cwd=str(root),
        status=status,
        generated_at=int(time.time()),
        release_checklist=str(Path(release.output_dir) / "release-checklist.md"),
        chaos_report=str(chaos.get("path") or chaos_checks.latest_path(root)),
        eval_report=str(eval_harness.reports_path(root)),
        daily_brief=str(brief.get("path") or ""),
        checks=[asdict(check) for check in release.checks],
        upgrade_notes=release.upgrade_notes,
        known_risks=_known_risks(release.known_risks, repair),
        rollback=release.rollback,
        push_package=_push_package(release),
    )
    data = {"schema": SCHEMA_VERSION, "candidate": rc.to_dict()}
    latest_path(root).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (rc_dir(root) / "release-candidate.md").write_text(format_candidate(rc) + "\n", encoding="utf-8")
    settings.restrict_file_permissions(latest_path(root))
    settings.restrict_file_permissions(rc_dir(root) / "release-candidate.md")
    return rc.to_dict()


def snapshot(cwd: str | Path, runtime_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    path = latest_path(cwd)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        candidate = data.get("candidate") if isinstance(data, dict) else {}
        if isinstance(candidate, dict):
            return {**candidate, "path": str(path)}
    runtime = runtime_snapshot if isinstance(runtime_snapshot, dict) else {}
    chaos = runtime.get("chaosChecks") if isinstance(runtime.get("chaosChecks"), dict) else {}
    repair = runtime.get("repairDoctor") if isinstance(runtime.get("repairDoctor"), dict) else {}
    onboarding = runtime.get("onboarding") if isinstance(runtime.get("onboarding"), dict) else {}
    return {
        "version": VERSION,
        "status": "not-generated",
        "path": str(path),
        "readiness": {
            "chaos": chaos.get("status") or "unknown",
            "repair": repair.get("status") or "unknown",
            "onboarding": onboarding.get("status") or "unknown",
        },
        "known_risks": ["Run `python main.py release` or `release_candidate.generate` to create the 1.0 RC manifest."],
        "push_package": _default_push_package(),
    }


def prompt_section(cwd: str | Path, runtime_snapshot: dict[str, Any] | None = None) -> str:
    data = snapshot(cwd, runtime_snapshot)
    if data.get("status") == "pass":
        return ""
    lines = ["# Crypt 1.0 Release Candidate"]
    lines.append(f"- status={data.get('status')}; path={data.get('path')}")
    for risk in data.get("known_risks") or []:
        lines.append(f"- risk={risk}")
    return "\n".join(lines)


def format_candidate(candidate: ReleaseCandidate) -> str:
    lines = [
        f"# Crypt {candidate.version} Release Candidate",
        "",
        f"- Status: {candidate.status.upper()}",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(candidate.generated_at))}",
        f"- Release checklist: `{candidate.release_checklist}`",
        f"- Chaos report: `{candidate.chaos_report}`",
        f"- Eval report: `{candidate.eval_report}`",
        f"- Daily brief: `{candidate.daily_brief}`",
        "",
        "## Checks",
    ]
    lines.extend(f"- {'PASS' if item.get('ok') else 'FAIL'} `{item.get('command')}`" for item in candidate.checks)
    lines.extend(["", "## Upgrade Notes"])
    lines.extend(f"- {item}" for item in candidate.upgrade_notes)
    lines.extend(["", "## Known Risks"])
    lines.extend(f"- {item}" for item in candidate.known_risks)
    lines.extend(["", "## Rollback"])
    lines.extend(f"- {item}" for item in candidate.rollback)
    lines.extend(["", "## Push / PR Package"])
    lines.extend(f"- {item}" for item in candidate.push_package)
    return "\n".join(lines)


def _known_risks(release_risks: list[str], repair: dict[str, Any]) -> list[str]:
    risks = list(release_risks or [])
    if int(repair.get("failing") or 0):
        risks.append(f"Repair doctor has {repair.get('failing')} failing item(s): {repair.get('summary')}")
    return risks or ["No known release risk recorded."]


def _push_package(release: release_train.ReleaseReport) -> list[str]:
    return [
        f"Branch: `{release.branch}`",
        f"Commit: `{release.commit}`",
        "Push command after final verification: `git push origin main`",
        "PR body should include release checklist, chaos report, eval report, known risks, and rollback notes.",
        "Do not include local auth, `.env`, voice cache, or generated private user state.",
    ]


def _default_push_package() -> list[str]:
    return [
        "Run final verification.",
        "Commit only intentional files.",
        "Push to GitHub after checks pass.",
        "Attach release checklist, risks, and rollback plan to PR or release notes.",
    ]
