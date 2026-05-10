from __future__ import annotations

import glob as _glob
import os
from pathlib import Path

from .fs import SKIP_DIRS, int_arg, rel, root
from .types import Tool


def run(args: dict) -> str:
    pattern = str(args["pattern"]).strip()
    if not pattern:
        return "(no pattern)"

    base = root()
    full_pattern = pattern if os.path.isabs(pattern) else str(base / pattern)
    recursive = "**" in pattern

    matches: list[Path] = []
    for entry in _glob.iglob(full_pattern, recursive=recursive):
        p = Path(entry)
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            p.resolve().relative_to(base)
        except ValueError:
            continue
        matches.append(p)

    matches.sort(
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )

    limit = int_arg(args, "limit", 100, 1000)
    truncated = len(matches) > limit
    matches = matches[:limit]

    if not matches:
        return "(no matches)"

    out = "\n".join(rel(p) for p in matches)
    if truncated:
        out += f"\n... ({len(matches)}+ shown, narrow the pattern for more)"
    return out


def summary(args: dict) -> str:
    return str(args.get("pattern", ""))


TOOL = Tool(
    "glob",
    (
        "Find files by glob pattern. Patterns like `**/*.py`, `src/**/*.ts`, or "
        "`tests/test_*.py` are supported. Returns paths sorted by mtime (most recent "
        "first). Use this to locate files by name; use grep to search file contents."
    ),
    {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["pattern"],
    },
    "auto",
    run,
    priority=15,
    summary=summary,
    parallel_safe=True,
)
