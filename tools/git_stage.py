from __future__ import annotations

import subprocess
from pathlib import Path

from .fs import root
from .types import Tool


def run(args: dict) -> str:
    action = str(args.get("action", "stage")).strip().lower()
    if action not in {"stage", "unstage"}:
        raise ValueError("action must be stage or unstage")

    all_changes = bool(args.get("all"))
    paths = _paths(args.get("paths") or [])
    if not all_changes and not paths:
        raise ValueError("provide paths or all=true")

    if action == "stage":
        cmd = ["add", "-A"] if all_changes else ["add", "--", *paths]
    else:
        cmd = ["restore", "--staged"]
        if all_changes:
            cmd.append(".")
        else:
            cmd.extend(["--", *paths])

    rc, out, err = _run_git(cmd)
    body = "\n".join(x.rstrip() for x in (out, err) if x.strip()).strip()
    if rc != 0:
        raise RuntimeError(f"git {action}: exit {rc}\n{body or '(no output)'}")
    target = "all changes" if all_changes else ", ".join(paths)
    return f"{action}d {target}"


def _paths(raw_paths) -> list[str]:
    base = root()
    out: list[str] = []
    for item in raw_paths:
        raw = str(item).strip()
        if not raw:
            continue
        p = Path(raw)
        resolved = (p if p.is_absolute() else base / p).resolve()
        try:
            rel = resolved.relative_to(base)
        except ValueError as e:
            raise PermissionError(f"path outside workspace: {raw}") from e
        out.append(str(rel))
    return out


def _run_git(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git", "-C", str(root()), *cmd],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        raise RuntimeError("git is not installed or not on PATH") from e
    return r.returncode, r.stdout or "", r.stderr or ""


def summary(args: dict) -> str:
    action = str(args.get("action", "stage"))
    if args.get("all"):
        return f"{action} all"
    paths = args.get("paths") or []
    return f"{action} {', '.join(str(p) for p in paths) or '(none)'}"


PROMPT = """
Use git_stage for explicit index changes. Prefer staging exact paths over
all=true unless the user asked to commit the entire current worktree. Always
inspect git status/diff before staging.
""".strip()


TOOL = Tool(
    "git_stage",
    "Stage or unstage Git changes in the workspace index. Requires user approval.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["stage", "unstage"]},
            "paths": {"type": "array", "items": {"type": "string"}},
            "all": {"type": "boolean", "description": "Stage/unstage all changes."},
        },
        "required": ["action"],
    },
    "ask",
    run,
    prompt=PROMPT,
    priority=44,
    summary=summary,
    available_in_subagent=False,
)
