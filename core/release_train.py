"""Repeatable release checklist generation for CryptCore."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import settings


DEFAULT_CHECKS = [
    "scripts\\verify_core.ps1 -Quick",
    "python main.py bench --bench-list",
]


@dataclass(frozen=True)
class ReleaseCheck:
    command: str
    ok: bool
    returncode: int
    duration_ms: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class ReleaseReport:
    release_id: str
    version: str
    cwd: str
    branch: str
    commit: str
    generated_at: int
    output_dir: str
    checks: list[ReleaseCheck]
    changelog: list[str] = field(default_factory=list)
    upgrade_notes: list[str] = field(default_factory=list)
    known_risks: list[str] = field(default_factory=list)
    rollback: list[str] = field(default_factory=list)
    github_flow: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks) and not any(
            risk.startswith("BLOCKER:") for risk in self.known_risks
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def generate(
    cwd: str | Path,
    *,
    checks: list[str] | None = None,
    output_root: str | Path | None = None,
    run_checks: bool = True,
) -> ReleaseReport:
    root = Path(cwd).expanduser().resolve()
    release_id = time.strftime("%Y%m%d-%H%M%S")
    out_root = Path(output_root).expanduser().resolve() if output_root else settings.APP_DIR / "release-train"
    out_dir = out_root / release_id
    out_dir.mkdir(parents=True, exist_ok=True)
    check_commands = list(checks or DEFAULT_CHECKS)
    results = [_run_check(command, root) for command in check_commands] if run_checks else [
        ReleaseCheck(command=command, ok=False, returncode=125, duration_ms=0, stderr="not run")
        for command in check_commands
    ]
    report = ReleaseReport(
        release_id=release_id,
        version=_project_version(root),
        cwd=str(root),
        branch=_git(["rev-parse", "--abbrev-ref", "HEAD"], root) or "unknown",
        commit=_git(["rev-parse", "--short", "HEAD"], root) or "unknown",
        generated_at=int(time.time()),
        output_dir=str(out_dir),
        checks=results,
        changelog=_changelog(root),
        upgrade_notes=_upgrade_notes(root),
        known_risks=_known_risks(root, results),
        rollback=_rollback(root),
        github_flow=_github_flow(),
        screenshots=_screenshots(root),
    )
    (out_dir / "release-checklist.json").write_text(report.to_json(), encoding="utf-8")
    (out_dir / "release-checklist.md").write_text(format_report(report) + "\n", encoding="utf-8")
    return report


def format_report(report: ReleaseReport) -> str:
    lines = [
        f"# Crypt Release Checklist {report.release_id}",
        "",
        f"- Version: {report.version}",
        f"- Branch: {report.branch}",
        f"- Commit: {report.commit}",
        f"- Status: {'PASS' if report.success else 'BLOCKED'}",
        f"- Output: {report.output_dir}",
        "",
        "## Verification",
    ]
    for check in report.checks:
        mark = "PASS" if check.ok else "FAIL"
        lines.append(f"- {mark} `{check.command}` ({check.duration_ms} ms)")
    lines.extend(["", "## Changelog"])
    lines.extend(f"- {item}" for item in (report.changelog or ["No git changelog found."]))
    lines.extend(["", "## Upgrade Notes"])
    lines.extend(f"- {item}" for item in report.upgrade_notes)
    lines.extend(["", "## Known Risks"])
    lines.extend(f"- {item}" for item in report.known_risks)
    lines.extend(["", "## Rollback"])
    lines.extend(f"- {item}" for item in report.rollback)
    lines.extend(["", "## GitHub Flow"])
    lines.extend(f"- {item}" for item in report.github_flow)
    if report.screenshots:
        lines.extend(["", "## Screenshots"])
        lines.extend(f"- {item}" for item in report.screenshots)
    return "\n".join(lines)


def _run_check(command: str, cwd: Path) -> ReleaseCheck:
    started = time.perf_counter()
    result = subprocess.run(command, cwd=cwd, shell=True, capture_output=True, text=True, timeout=300)
    return ReleaseCheck(
        command=command,
        ok=result.returncode == 0,
        returncode=result.returncode,
        duration_ms=int((time.perf_counter() - started) * 1000),
        stdout=_tail(result.stdout),
        stderr=_tail(result.stderr),
    )


def _project_version(cwd: Path) -> str:
    pyproject = cwd / "pyproject.toml"
    if not pyproject.exists():
        return "unknown"
    for line in pyproject.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    return "unknown"


def _changelog(cwd: Path) -> list[str]:
    raw = _git(["log", "--oneline", "-n", "12"], cwd)
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _upgrade_notes(cwd: Path) -> list[str]:
    notes = [
        "Run the verification commands before pushing.",
        "Restart the WebUI after backend or static asset changes.",
        "For remote/mobile WebUI, provide an access token and limited scopes.",
    ]
    if (cwd / "scripts" / "setup_kokoro_voice.ps1").exists():
        notes.append("Run `scripts\\setup_kokoro_voice.ps1` if local Kokoro voice assets are missing.")
    return notes


def _known_risks(cwd: Path, checks: list[ReleaseCheck]) -> list[str]:
    risks = []
    failed = [check.command for check in checks if not check.ok]
    if failed:
        risks.append("BLOCKER: failing release checks: " + ", ".join(failed))
    dirty = _git(["status", "--short"], cwd)
    if dirty:
        risks.append("Working tree has uncommitted changes; release only after staging intentional files.")
    if not _screenshots(cwd):
        risks.append("No screenshot artifact detected; capture one for UI-heavy releases.")
    return risks or ["No blocking risk detected by the release generator."]


def _rollback(cwd: Path) -> list[str]:
    commit = _git(["rev-parse", "--short", "HEAD"], cwd) or "<commit>"
    previous = _git(["rev-parse", "--short", "HEAD~1"], cwd) or "<previous-commit>"
    return [
        f"Preferred: `git revert {commit}` and push the revert.",
        f"Emergency local-only: inspect `{previous}`, then coordinate before resetting any shared branch.",
        "Restore WebUI state from a `release-train` or `/api/backup` artifact if user state was affected.",
    ]


def _github_flow() -> list[str]:
    return [
        "Stage only intentional files.",
        "Commit with a user-facing summary and verification note.",
        "Push the release branch or `main` only after checks pass.",
        "For PR flow, open a draft PR with changelog, checks, screenshots, risks, and rollback notes.",
        "Never include auth tokens, `.env`, private keys, or local voice/cache artifacts.",
    ]


def _screenshots(cwd: Path) -> list[str]:
    candidates = []
    for folder in (cwd / "docs", settings.APP_DIR / "screenshots"):
        if folder.exists():
            candidates.extend(str(path) for path in folder.rglob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    return sorted(candidates)[:12]


def _git(args: list[str], cwd: Path) -> str:
    if shutil.which("git") is None:
        return ""
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else ""


def _tail(text: str, limit: int = 1600) -> str:
    clean = str(text or "").strip()
    return clean[-limit:] if len(clean) > limit else clean
