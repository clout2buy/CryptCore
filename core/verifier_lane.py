"""Structured verifier lane for targeted checks and durable evidence."""
from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from . import artifact_studio, evidence, session, settings, work_threads


@dataclass(frozen=True)
class VerificationCheck:
    name: str
    argv: list[str]
    kind: str = "unit"
    required: bool = True

    @property
    def command(self) -> str:
        return _command(self.argv)


@dataclass(frozen=True)
class VerificationCheckResult:
    name: str
    command: str
    kind: str
    ok: bool
    returncode: int
    duration_ms: int
    output: str = ""
    required: bool = True


@dataclass(frozen=True)
class VerificationLaneReport:
    report_id: str
    cwd: str
    status: str
    changed_files: list[str] = field(default_factory=list)
    checks: list[VerificationCheckResult] = field(default_factory=list)
    report_path: str = ""
    thread_id: str = ""
    created_at: int = 0


def plan_checks(
    cwd: str | Path,
    *,
    changed_files: list[str] | None = None,
    include_browser: bool = False,
    quick: bool = False,
) -> list[VerificationCheck]:
    root = Path(cwd).expanduser().resolve()
    changed = _existing_rel_paths(root, changed_files or [])
    py_files = [path for path in changed if path.endswith(".py")]
    js_files = [path for path in changed if path.endswith(".js")]
    web_files = [path for path in changed if path.endswith((".html", ".css", ".js", ".ts", ".tsx", ".jsx"))]
    test_files = [path for path in py_files if _is_test_path(path)]
    checks: list[VerificationCheck] = []
    if py_files:
        checks.append(VerificationCheck("python syntax", ["python", "-m", "py_compile", *py_files], "syntax"))
    for path in js_files[:4]:
        checks.append(VerificationCheck(f"node syntax {path}", ["node", "--check", path], "syntax"))
    if (root / "tests").exists() and (py_files or test_files):
        target = test_files or ["tests"]
        checks.append(VerificationCheck("pytest", ["pytest", *target], "unit"))
    if include_browser and web_files:
        checks.append(VerificationCheck("browser qa required", ["browser-qa", "manual", *web_files[:3]], "browser", required=False))
    if quick and (root / "scripts" / "verify_core.ps1").exists():
        checks.append(
            VerificationCheck(
                "repo quick smoke",
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts\\verify_core.ps1", "-Quick"],
                "release",
            )
        )
    if not checks:
        checks.append(VerificationCheck("diff whitespace", ["git", "diff", "--check"], "lint"))
    return checks


def run_verification(
    cwd: str | Path,
    *,
    changed_files: list[str] | None = None,
    thread_id: str = "",
    include_browser: bool = False,
    quick: bool = False,
    timeout_seconds: int = 120,
) -> VerificationLaneReport:
    root = Path(cwd).expanduser().resolve()
    checks = plan_checks(root, changed_files=changed_files, include_browser=include_browser, quick=quick)
    results = [_run_check(root, check, timeout_seconds=timeout_seconds) for check in checks]
    status = _status(results)
    report = VerificationLaneReport(
        report_id="verify_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        status=status,
        changed_files=_existing_rel_paths(root, changed_files or []),
        checks=results,
        thread_id=thread_id,
        created_at=int(time.time()),
    )
    report = _write_report(root, report)
    record_report(report, thread_id=thread_id)
    return report


def record_report(report: VerificationLaneReport, *, thread_id: str = "") -> evidence.EvidenceEntry:
    findings = [
        f"{check.name}: {check.output[:500]}"
        for check in report.checks
        if not check.ok and check.output
    ]
    result = evidence.VerificationResult(
        status=report.status,
        commands=[check.command for check in report.checks],
        findings=findings,
        risk="" if report.status == "PASS" else "verification did not fully pass",
        task_id=thread_id or None,
    )
    entry = evidence.record_verification(result, source="verifier-lane")
    if thread_id:
        _attach_to_thread(report, thread_id)
    if report.report_path:
        artifact_studio.record_artifact(
            report.cwd,
            report.report_path,
            thread_id=thread_id,
            kind="data",
            status="verified" if report.status == "PASS" else "failed",
            provenance="verifier-lane",
            source="verifier-lane",
            attach_recent=not bool(thread_id),
        )
    return entry


def _run_check(root: Path, check: VerificationCheck, *, timeout_seconds: int) -> VerificationCheckResult:
    started = time.perf_counter()
    if check.argv[:2] == ["browser-qa", "manual"]:
        return VerificationCheckResult(
            name=check.name,
            command=check.command,
            kind=check.kind,
            ok=True,
            returncode=0,
            duration_ms=0,
            output="Browser QA requested; run visually in the app browser when a local target is available.",
            required=check.required,
        )
    try:
        completed = subprocess.run(
            check.argv,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        return VerificationCheckResult(
            name=check.name,
            command=check.command,
            kind=check.kind,
            ok=completed.returncode == 0,
            returncode=completed.returncode,
            duration_ms=int((time.perf_counter() - started) * 1000),
            output=output[-2000:],
            required=check.required,
        )
    except Exception as exc:
        return VerificationCheckResult(
            name=check.name,
            command=check.command,
            kind=check.kind,
            ok=False,
            returncode=1,
            duration_ms=int((time.perf_counter() - started) * 1000),
            output=f"{type(exc).__name__}: {exc}",
            required=check.required,
        )


def _write_report(root: Path, report: VerificationLaneReport) -> VerificationLaneReport:
    path = session.project_dir(root) / "verification" / f"{report.report_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(report)
    data["report_path"] = str(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.restrict_file_permissions(path)
    return replace(report, report_path=str(path))


def _attach_to_thread(report: VerificationLaneReport, thread_id: str) -> None:
    passed = sum(1 for check in report.checks if check.ok)
    total = len(report.checks)
    try:
        work_threads.update_thread(
            thread_id,
            last_note=f"verification {report.status}: {passed}/{total} checks passed",
            artifacts=[report.report_path] if report.report_path else None,
            source="verifier-lane",
        )
    except Exception:
        return


def _status(results: list[VerificationCheckResult]) -> str:
    if not results:
        return "SKIPPED"
    required = [result for result in results if result.required]
    if required and all(result.ok for result in required):
        return "PASS"
    if any(not result.ok for result in required):
        return "FAIL"
    return "PARTIAL"


def _existing_rel_paths(root: Path, paths: list[str]) -> list[str]:
    out: list[str] = []
    for item in paths:
        path = Path(str(item).replace("\\", "/"))
        candidate = (root / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            rel = str(candidate.relative_to(root))
        except ValueError:
            continue
        if candidate.exists() and rel not in out:
            out.append(rel)
    return out


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    return normalized.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py")


def _command(argv: list[str]) -> str:
    return " ".join(_quote(part) for part in argv)


def _quote(part: str) -> str:
    text = str(part)
    if not text or any(char.isspace() for char in text):
        return '"' + text.replace('"', '\\"') + '"'
    return text
