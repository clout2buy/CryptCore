"""Credential and secret hygiene helpers."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import redact


SECRET_PATTERNS = (
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("secret-assignment", re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password|credential)\b\s*[:=]\s*[^\s]+")),
    ("credit-card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
)
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}
TEXT_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".html", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".env", ""}


@dataclass(frozen=True)
class SecretFinding:
    kind: str
    file: str
    line: int
    excerpt: str
    severity: str = "high"


def scan_text(text: str, *, file: str = "<text>") -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    value = str(text or "")
    for index, line in enumerate(value.splitlines() or [value], 1):
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(
                    SecretFinding(
                        kind=kind,
                        file=file,
                        line=index,
                        excerpt=redact.text(line.strip())[:240],
                        severity="critical" if kind in {"private-key", "credit-card"} else "high",
                    )
                )
                break
    return findings


def scan_workspace(cwd: str | Path, *, limit: int = 500) -> list[SecretFinding]:
    root = Path(cwd).expanduser().resolve()
    findings: list[SecretFinding] = []
    scanned = 0
    for path in root.rglob("*"):
        if scanned >= limit:
            break
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_EXTS and not path.name.endswith(".env"):
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings.extend(scan_text(text, file=_rel(root, path)))
    return findings


def safe_context(value: Any) -> Any:
    return redact.content(value)


def summary(findings: list[SecretFinding]) -> str:
    if not findings:
        return "No secret-looking values found."
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.kind] = counts.get(finding.kind, 0) + 1
    parts = [f"{kind}={count}" for kind, count in sorted(counts.items())]
    return "Secret scan findings: " + ", ".join(parts)


def snapshot(cwd: str | Path, *, limit: int = 500) -> dict[str, Any]:
    findings = scan_workspace(cwd, limit=limit)
    return {
        "summary": summary(findings),
        "findings": [asdict(finding) for finding in findings[:50]],
    }


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
