from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .fs import rel, resolve, within_root
from .types import Tool


_SAFE_GENERATED_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".txt", ".md",
}


def run(args: dict) -> str:
    raw = str(args["path"]).strip()
    if not raw:
        raise ValueError("path is required")

    p = Path(raw).expanduser()
    if not p.is_absolute():
        # Relative paths resolve under the workspace root.
        from .fs import resolve
        p = resolve(raw)
    else:
        p = p.resolve()

    if not p.exists():
        raise FileNotFoundError(str(p))

    if os.name == "nt":
        os.startfile(p)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(p)])
    try:
        from core import artifact_lifecycle

        artifact_lifecycle.record_open(p)
    except Exception:
        pass

    # Show workspace-relative when inside, absolute when outside.
    try:
        return f"opened {rel(p)}"
    except Exception:
        return f"opened {p}"


def summary(args: dict) -> str:
    return str(args.get("path", ""))


def classify(args: dict) -> str | None:
    raw = str(args.get("path", "")).strip()
    if not raw or not within_root(raw):
        return "ask"
    try:
        path = resolve(raw)
    except Exception:
        return "ask"
    suffix = path.suffix.lower()
    if suffix not in _SAFE_GENERATED_EXTS:
        return "ask"
    try:
        from core import artifact_lifecycle

        return "safe" if artifact_lifecycle.was_written(path) else "ask"
    except Exception:
        return "ask"


TOOL = Tool(
    "open_file",
    (
        "Open a file in the system default app (image viewer, browser, etc). "
        "Read-only — does not modify anything. Accepts absolute paths anywhere "
        "on disk; relative paths resolve under the workspace."
    ),
    {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    "ask",
    run,
    priority=70,
    summary=summary,
    classify=classify,
)
