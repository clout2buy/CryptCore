"""Durable user/project memory for Crypt."""
from __future__ import annotations

import os
import time
from pathlib import Path

from . import settings


MEMORY_DIR = settings.APP_DIR / "memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"


def ensure_memory() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_INDEX.exists():
        MEMORY_INDEX.write_text(
            "# Crypt Memory\n\n"
            "Durable facts and workflow preferences that Crypt should remember.\n\n"
            "## User\n\n"
            "## Projects\n\n"
            "## Workflow\n\n",
            encoding="utf-8",
        )
        if os.name != "nt":
            try:
                os.chmod(MEMORY_INDEX, 0o600)
            except OSError:
                pass


def read_memory(limit: int = 12_000) -> str:
    ensure_memory()
    try:
        text = MEMORY_INDEX.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text if len(text) <= limit else text[:limit] + "\n... [memory truncated]"


def add_memory(text: str, scope: str = "Workflow") -> str:
    ensure_memory()
    clean = " ".join(text.strip().split())
    if not clean:
        raise ValueError("memory text cannot be empty")
    scope = scope.strip().title() or "Workflow"
    stamp = time.strftime("%Y-%m-%d")
    line = f"- {stamp}: {clean}\n"
    current = MEMORY_INDEX.read_text(encoding="utf-8", errors="replace")
    header = f"## {scope}"
    if header in current:
        current = current.replace(header, header + "\n" + line, 1)
    else:
        current = current.rstrip() + f"\n\n{header}\n{line}"
    MEMORY_INDEX.write_text(current, encoding="utf-8")
    return f"remembered under {scope}: {clean}"


def project_instruction_files(cwd: str | Path) -> list[Path]:
    start = Path(cwd).expanduser().resolve()
    names = ("CRYPT.md", "AGENTS.md", "CLAUDE.md", ".crypt/instructions.md")
    out: list[Path] = []
    cur = start
    home = Path.home().resolve()
    while True:
        for name in names:
            p = cur / name
            if p.exists() and p.is_file():
                out.append(p)
        if cur == cur.parent:
            break
        # Stop above home unless the workspace itself is outside home.
        if cur == home:
            break
        cur = cur.parent
    return out


def load_project_instructions(cwd: str | Path, limit: int = 20_000) -> str:
    chunks: list[str] = []
    used = 0
    for path in project_instruction_files(cwd):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        header = f"## {path}\n"
        remaining = limit - used - len(header)
        if remaining <= 0:
            break
        body = text[:remaining]
        chunks.append(header + body)
        used += len(header) + len(body)
    return "\n\n".join(chunks)

