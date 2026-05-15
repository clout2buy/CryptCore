"""Deterministic reviewer lane for nontrivial changes."""
from __future__ import annotations

import re
from pathlib import Path

from . import target_eval


ReviewFinding = target_eval.ReviewFinding

_CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx"}
_UI_EXTS = {".css", ".html", ".js", ".ts", ".tsx", ".jsx"}
_EVAL_RE = re.compile(r"\b(eval|exec)\s*\(")
_SHELL_TRUE_RE = re.compile(r"\bshell\s*=\s*True\b")
_PASS_EXCEPT_RE = re.compile(r"except\s+Exception\s*:\s*(?:\n\s*)?pass\b", re.MULTILINE)
_INNER_HTML_RE = re.compile(r"\.innerHTML\s*=")
_VW_FONT_RE = re.compile(r"font-size\s*:\s*[^;]*vw\b", re.I)
_TRANSITION_ALL_RE = re.compile(r"transition\s*:\s*all\b", re.I)


def review_changes(
    before_dir: str | Path,
    after_dir: str | Path,
    *,
    changed_files: list[str] | None = None,
    trace_path: str | Path | None = None,
    forbidden_accessed: list[str] | None = None,
    removed_artifacts: list[str] | None = None,
) -> list[ReviewFinding]:
    """Run target-eval checks plus the dedicated reviewer heuristics."""
    before = Path(before_dir).resolve()
    after = Path(after_dir).resolve()
    changed = changed_files if changed_files is not None else target_eval.changed_paths(before, after)
    findings = target_eval.review_changes(
        before,
        after,
        changed_files=changed,
        trace_path=trace_path,
        forbidden_accessed=forbidden_accessed,
        removed_artifacts=removed_artifacts,
    )
    findings.extend(_review_unsafe_code(after, changed))
    findings.extend(_review_ui_quality(after, changed))
    return _dedupe_findings(findings)


def prompt_section() -> str:
    return (
        "# Reviewer Lane\n"
        "- For nontrivial changes, review for regressions, missing tests, unsafe assumptions, UI quality, and verification gaps.\n"
        "- Treat reviewer findings as blockers when priority is P1/P2 unless there is a concrete reason they do not apply."
    )


def _review_unsafe_code(after: Path, changed: list[str]) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for rel in changed:
        path = after / rel
        if path.suffix.lower() not in _CODE_EXTS or not path.exists() or path.is_dir():
            continue
        text = _read(path)
        findings.extend(_regex_findings(path, text, _EVAL_RE, "[P1] Dynamic code execution introduced", "Dynamic eval/exec is rarely safe in agent-controlled code. Replace it with explicit parsing or a constrained dispatch table.", 1, 0.9))
        findings.extend(_regex_findings(path, text, _SHELL_TRUE_RE, "[P2] Shell execution uses shell=True", "shell=True expands the command injection surface. Prefer an argv list and explicit quoting only when unavoidable.", 2, 0.86))
        findings.extend(_regex_findings(path, text, _PASS_EXCEPT_RE, "[P2] Broad exception is silently swallowed", "Swallowing every Exception hides regressions and makes autonomous recovery weaker. Handle the expected exception or record the failure.", 2, 0.82))
    return findings


def _review_ui_quality(after: Path, changed: list[str]) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for rel in changed:
        path = after / rel
        if path.suffix.lower() not in _UI_EXTS or not path.exists() or path.is_dir():
            continue
        text = _read(path)
        findings.extend(_regex_findings(path, text, _VW_FONT_RE, "[P3] Viewport-scaled font size", "Viewport-width font sizing often causes text to overflow or become tiny on edge viewports. Use responsive layout constraints with stable font sizes.", 3, 0.76))
        findings.extend(_regex_findings(path, text, _TRANSITION_ALL_RE, "[P3] Transition-all can animate layout accidentally", "transition: all can animate layout and create flicker. Name the properties that should animate.", 3, 0.7))
        for finding in _regex_findings(path, text, _INNER_HTML_RE, "[P2] Raw innerHTML assignment changed", "Raw innerHTML can create XSS or stale-render bugs. Use DOM APIs or guarantee every interpolated value is escaped.", 2, 0.7):
            if "escapeHtml" not in _line_at(text, finding.start):
                findings.append(finding)
    return findings


def _regex_findings(
    path: Path,
    text: str,
    pattern: re.Pattern[str],
    title: str,
    body: str,
    priority: int,
    confidence: float,
) -> list[ReviewFinding]:
    out: list[ReviewFinding] = []
    for match in pattern.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        out.append(
            ReviewFinding(
                title=title,
                body=body,
                file=str(path),
                start=line,
                priority=priority,
                confidence=confidence,
            )
        )
    return out


def _line_at(text: str, line_number: int) -> str:
    lines = text.splitlines()
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1]
    return ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _dedupe_findings(findings: list[ReviewFinding]) -> list[ReviewFinding]:
    seen: set[tuple[str, str, int]] = set()
    out: list[ReviewFinding] = []
    for finding in findings:
        key = (finding.title, finding.file, finding.start)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    out.sort(key=lambda item: (item.priority, item.file, item.start))
    return out
