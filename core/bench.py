"""Benchmark runner for Crypt agent quality.

Suites are JSON files that define isolated repo tasks. The runner creates a
fresh workspace for each task, runs the real non-interactive agent loop, then
scores the result with shell checks and git diff constraints.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Any

from . import loop, settings


DEFAULT_SUITE = Path(__file__).resolve().parent.parent / "benchmarks" / "smoke.json"


@dataclass
class CheckResult:
    command: str
    ok: bool
    returncode: int
    duration_ms: int
    stdout: str = ""
    stderr: str = ""


@dataclass
class BenchTask:
    id: str
    prompt: str
    files: dict[str, str]
    checks: list[str]
    description: str = ""
    setup: list[str] = field(default_factory=list)
    max_turns: int = 20
    timeout_seconds: int = 120
    forbidden_paths: list[str] = field(default_factory=list)
    forbidden_access_paths: list[str] = field(default_factory=list)
    required_changed_paths: list[str] = field(default_factory=list)
    allowed_changed_paths: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    id: str
    success: bool
    score: float
    workspace: str
    trace_path: str
    duration_ms: int
    checks: list[CheckResult] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    forbidden_changed: list[str] = field(default_factory=list)
    forbidden_accessed: list[str] = field(default_factory=list)
    missing_required_changes: list[str] = field(default_factory=list)
    unexpected_changes: list[str] = field(default_factory=list)
    final_text: str = ""
    error: str = ""


@dataclass
class SuiteReport:
    name: str
    run_id: str
    output_dir: str
    total: int
    passed: int
    pass_rate: float
    results: list[TaskResult]

    @property
    def success(self) -> bool:
        return self.total > 0 and self.passed == self.total

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def load_suite(path: str | Path = DEFAULT_SUITE) -> tuple[str, list[BenchTask]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("benchmark suite must be a JSON object")
    tasks_raw = data.get("tasks")
    if not isinstance(tasks_raw, list):
        raise ValueError("benchmark suite needs a 'tasks' array")
    tasks = [_task_from_dict(item) for item in tasks_raw]
    return str(data.get("name") or Path(path).stem), tasks


def list_tasks(path: str | Path = DEFAULT_SUITE) -> str:
    name, tasks = load_suite(path)
    lines = [f"{name}: {len(tasks)} task(s)"]
    for task in tasks:
        suffix = f" - {task.description}" if task.description else ""
        lines.append(f"- {task.id}{suffix}")
    return "\n".join(lines)


def run_suite(
    provider_factory: Callable[[], Any],
    *,
    suite_path: str | Path = DEFAULT_SUITE,
    output_root: str | Path | None = None,
    task_ids: list[str] | None = None,
    max_tasks: int | None = None,
) -> SuiteReport:
    suite_name, tasks = load_suite(suite_path)
    wanted = set(task_ids or [])
    if wanted:
        tasks = [task for task in tasks if task.id in wanted]
        missing = sorted(wanted.difference(task.id for task in tasks))
        if missing:
            raise ValueError(f"unknown benchmark task(s): {', '.join(missing)}")
    if max_tasks is not None:
        tasks = tasks[:max(0, max_tasks)]

    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    root = Path(output_root).expanduser().resolve() if output_root else settings.APP_DIR / "bench-runs"
    out_dir = root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[TaskResult] = []
    for task in tasks:
        provider = provider_factory()
        results.append(run_task(provider, task, out_dir))

    passed = sum(1 for result in results if result.success)
    total = len(results)
    report = SuiteReport(
        name=suite_name,
        run_id=run_id,
        output_dir=str(out_dir),
        total=total,
        passed=passed,
        pass_rate=passed / total if total else 0.0,
        results=results,
    )
    (out_dir / "report.json").write_text(report.to_json(), encoding="utf-8")
    return report


def run_task(provider, task: BenchTask, out_dir: Path) -> TaskResult:
    started = time.perf_counter()
    workspace = out_dir / task.id / "workspace"
    trace_path = out_dir / task.id / "trace.jsonl"
    workspace.mkdir(parents=True, exist_ok=True)
    _write_files(workspace, task.files)
    _ensure_gitignore(workspace)
    _init_git(workspace)

    old_trace = os.environ.get("CRYPT_TRACE_PATH")
    os.environ["CRYPT_TRACE_PATH"] = str(trace_path)
    try:
        setup_results = [_run_command(command, workspace, task.timeout_seconds) for command in task.setup]
        setup_failed = [result for result in setup_results if not result.ok]
        if setup_failed:
            return _task_failure(
                task,
                workspace,
                trace_path,
                started,
                checks=setup_results,
                error="setup failed",
            )

        run_result = loop.run_prompt(
            provider,
            task.prompt,
            cwd=str(workspace),
            max_turns=task.max_turns,
            approval_mode="all",
            render=False,
        )
        checks = [_run_command(command, workspace, task.timeout_seconds) for command in task.checks]
        changed = _git_changed_files(workspace)
        forbidden = _matched_paths(changed, task.forbidden_paths)
        forbidden_accessed = _matched_paths(_trace_accessed_paths(trace_path), task.forbidden_access_paths)
        missing = sorted(set(task.required_changed_paths).difference(changed))
        unexpected = _unexpected_changes(changed, task.allowed_changed_paths)
        checks_ok = all(result.ok for result in checks)
        success = checks_ok and not forbidden and not forbidden_accessed and not missing and not unexpected
        score = _score(checks, forbidden, forbidden_accessed, missing, unexpected)
        return TaskResult(
            id=task.id,
            success=success,
            score=score,
            workspace=str(workspace),
            trace_path=str(trace_path),
            duration_ms=int((time.perf_counter() - started) * 1000),
            checks=checks,
            changed_files=changed,
            forbidden_changed=forbidden,
            forbidden_accessed=forbidden_accessed,
            missing_required_changes=missing,
            unexpected_changes=unexpected,
            final_text=run_result.final_text[:2000],
        )
    except Exception as exc:
        return _task_failure(
            task,
            workspace,
            trace_path,
            started,
            checks=[],
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if old_trace is None:
            os.environ.pop("CRYPT_TRACE_PATH", None)
        else:
            os.environ["CRYPT_TRACE_PATH"] = old_trace


def format_report(report: SuiteReport) -> str:
    lines = [
        f"benchmark: {report.name}",
        f"run: {report.run_id}",
        f"passed: {report.passed}/{report.total} ({report.pass_rate:.0%})",
        f"output: {report.output_dir}",
    ]
    for result in report.results:
        mark = "PASS" if result.success else "FAIL"
        detail = ""
        if result.error:
            detail = f" - {result.error}"
        elif not result.success:
            failed_checks = sum(1 for check in result.checks if not check.ok)
            parts = []
            if failed_checks:
                parts.append(f"{failed_checks} check(s) failed")
            if result.forbidden_changed:
                parts.append(f"forbidden changed: {', '.join(result.forbidden_changed)}")
            if result.forbidden_accessed:
                parts.append(f"forbidden accessed: {', '.join(result.forbidden_accessed)}")
            if result.missing_required_changes:
                parts.append(f"missing changes: {', '.join(result.missing_required_changes)}")
            if result.unexpected_changes:
                parts.append(f"unexpected changes: {', '.join(result.unexpected_changes)}")
            detail = " - " + "; ".join(parts) if parts else ""
        lines.append(f"{mark} {result.id} score={result.score:.2f}{detail}")
    return "\n".join(lines)


def _task_from_dict(data: Any) -> BenchTask:
    if not isinstance(data, dict):
        raise ValueError("benchmark task must be an object")
    files = data.get("files")
    checks = data.get("checks")
    if not isinstance(files, dict) or not isinstance(checks, list):
        raise ValueError("benchmark task needs 'files' object and 'checks' array")
    return BenchTask(
        id=str(data["id"]),
        description=str(data.get("description") or ""),
        prompt=str(data["prompt"]),
        files={str(path): str(content) for path, content in files.items()},
        checks=[str(command) for command in checks],
        setup=[str(command) for command in data.get("setup", [])],
        max_turns=int(data.get("max_turns") or 20),
        timeout_seconds=int(data.get("timeout_seconds") or 120),
        forbidden_paths=[str(path) for path in data.get("forbidden_paths", [])],
        forbidden_access_paths=[str(path) for path in data.get("forbidden_access_paths", [])],
        required_changed_paths=[str(path) for path in data.get("required_changed_paths", [])],
        allowed_changed_paths=[str(path) for path in data.get("allowed_changed_paths", [])],
    )


def _write_files(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = (root / name).resolve()
        if not _within(root, path):
            raise ValueError(f"benchmark file escapes workspace: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _ensure_gitignore(root: Path) -> None:
    ignored = [
        "__pycache__/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".coverage",
        "*.pyc",
    ]
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    lines = existing.splitlines()
    changed = False
    for item in ignored:
        if item not in lines:
            lines.append(item)
            changed = True
    if changed:
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _init_git(root: Path) -> None:
    if shutil.which("git") is None:
        return
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "crypt-bench@example.invalid"],
        ["git", "config", "user.name", "Crypt Bench"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "bench seed"],
    ]
    for command in commands:
        subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=30)


def _run_command(command: str, cwd: Path, timeout: int) -> CheckResult:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CheckResult(
            command=command,
            ok=result.returncode == 0,
            returncode=result.returncode,
            duration_ms=int((time.perf_counter() - started) * 1000),
            stdout=_tail(result.stdout),
            stderr=_tail(result.stderr),
        )
    except subprocess.TimeoutExpired as exc:
        return CheckResult(
            command=command,
            ok=False,
            returncode=124,
            duration_ms=int((time.perf_counter() - started) * 1000),
            stdout=_tail(exc.stdout or ""),
            stderr=_tail(exc.stderr or "timed out"),
        )


def _git_changed_files(root: Path) -> list[str]:
    if shutil.which("git") is None:
        return []
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    out: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        out.append(line[3:].strip().replace("\\", "/"))
    return sorted(out)


def _matched_paths(changed: list[str], patterns: list[str]) -> list[str]:
    if not patterns:
        return []
    import fnmatch

    matches: list[str] = []
    for path in changed:
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
            matches.append(path)
    return sorted(matches)


def _unexpected_changes(changed: list[str], allowed: list[str]) -> list[str]:
    if not allowed:
        return []
    allowed_set = set(allowed)
    return sorted(path for path in changed if path not in allowed_set)


def _trace_accessed_paths(trace_path: Path) -> list[str]:
    if not trace_path.exists():
        return []
    paths: set[str] = set()
    try:
        events = json.loads("[" + ",".join(trace_path.read_text(encoding="utf-8").splitlines()) + "]")
    except (OSError, json.JSONDecodeError):
        return []
    for event in events:
        if not isinstance(event, dict) or event.get("event") != "tool_start":
            continue
        args = event.get("args")
        if isinstance(args, dict):
            paths.update(_paths_from_tool_args(args))
    return sorted(paths)


def _paths_from_tool_args(args: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    raw = args.get("path")
    if isinstance(raw, str) and raw:
        out.add(raw.replace("\\", "/"))
    edits = args.get("edits")
    if isinstance(edits, list):
        for item in edits:
            if isinstance(item, dict):
                raw_path = item.get("path")
                if isinstance(raw_path, str) and raw_path:
                    out.add(raw_path.replace("\\", "/"))
    return out


def _score(
    checks: list[CheckResult],
    forbidden: list[str],
    forbidden_accessed: list[str],
    missing: list[str],
    unexpected: list[str],
) -> float:
    if not checks:
        base = 0.0
    else:
        base = sum(1 for check in checks if check.ok) / len(checks)
    penalty = 0.15 * (len(forbidden) + len(missing) + len(unexpected))
    penalty += 0.25 * len(forbidden_accessed)
    return max(0.0, min(1.0, base - penalty))


def _task_failure(
    task: BenchTask,
    workspace: Path,
    trace_path: Path,
    started: float,
    *,
    checks: list[CheckResult],
    error: str,
) -> TaskResult:
    return TaskResult(
        id=task.id,
        success=False,
        score=0.0,
        workspace=str(workspace),
        trace_path=str(trace_path),
        duration_ms=int((time.perf_counter() - started) * 1000),
        checks=checks,
        changed_files=_git_changed_files(workspace),
        error=error,
    )


def _within(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]
