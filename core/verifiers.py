"""Verifier result parsing and recording."""
from __future__ import annotations

import re

from . import evidence
from .evidence import VerificationResult


_VERDICT_RE = re.compile(r"\bVERDICT:\s*(PASS|FAIL|PARTIAL|SKIPPED)\b", re.I)
_COMMAND_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:command|check|ran):\s*(.+)$", re.I | re.M)


def parse_verdict(text: str) -> str:
    match = _VERDICT_RE.search(str(text or ""))
    return match.group(1).upper() if match else "PARTIAL"


def parse_verifier_output(text: str, *, task_id: str | None = None) -> VerificationResult:
    raw = str(text or "")
    status = parse_verdict(raw)
    commands = [m.group(1).strip() for m in _COMMAND_RE.finditer(raw)]
    findings: list[str] = []
    risk = ""
    for line in raw.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith(("finding:", "- finding:", "* finding:")):
            findings.append(stripped.split(":", 1)[-1].strip())
        elif lowered.startswith(("risk:", "- risk:", "* risk:")):
            risk = stripped.split(":", 1)[-1].strip()
    if status in {"FAIL", "PARTIAL"} and not findings:
        findings = [_clip(raw, 1000)] if raw.strip() else ["Verifier did not provide findings."]
    return VerificationResult(status=status, commands=commands, findings=findings, risk=risk, task_id=task_id)


def record_verifier_output(text: str, *, task_id: str | None = None) -> VerificationResult:
    result = parse_verifier_output(text, task_id=task_id)
    evidence.record_verification(result, source="verifier")
    return result


def verifier_prompt(task: str, *, changed_files: list[str] | None = None) -> str:
    files = ", ".join(changed_files or []) or "(unknown)"
    return (
        "You are Crypt's independent verifier. Be adversarial and evidence-driven.\n"
        "Run or recommend the narrowest meaningful checks available. Do not edit project files.\n"
        "Your final response must contain `VERDICT: PASS`, `VERDICT: FAIL`, or `VERDICT: PARTIAL`.\n"
        f"Task: {task}\nChanged files: {files}"
    )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "... [truncated]"
