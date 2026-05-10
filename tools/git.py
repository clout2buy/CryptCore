from __future__ import annotations

import subprocess

from .fs import clip, root
from .types import Tool


def run(args: dict) -> str:
    action = str(args.get("action", "status")).strip().lower()
    if not _inside_work_tree():
        return (
            f"Git is not available for this workspace because {root()} is not inside a git repository. "
            "Switch the workspace to a repo folder or initialize git before asking for status/diff/log."
        )

    if action == "status":
        cmd = ["status", "-sb"]
    elif action == "diff":
        cmd = ["diff", "--no-color"]
        if args.get("staged"):
            cmd.append("--cached")
        if args.get("path"):
            cmd.extend(["--", str(args["path"])])
    elif action == "log":
        n = max(1, min(int(args.get("n") or 20), 200))
        cmd = ["log", "--oneline", "--decorate", "-n", str(n)]
        if args.get("path"):
            cmd.extend(["--", str(args["path"])])
    elif action == "show":
        commit = str(args.get("commit") or "HEAD")
        cmd = ["show", "--stat", "--no-color", commit]
    else:
        raise ValueError(f"unknown action: {action!r} (use status, diff, log, or show)")

    rc, out, err = _run_git(cmd)
    body = out.rstrip()
    if err.strip():
        body = (body + "\n[stderr]\n" + err.rstrip()).strip()
    if not body:
        body = "(no output)"

    if rc != 0:
        raise RuntimeError(f"git {action}: exit {rc}\n{body}")
    return clip(body, 20_000)


def summary(args: dict) -> str:
    action = str(args.get("action", "status"))
    bits: list[str] = []
    if args.get("path"):
        bits.append(str(args["path"]))
    if args.get("staged"):
        bits.append("staged")
    if args.get("commit"):
        bits.append(str(args["commit"]))
    if action == "log" and args.get("n"):
        bits.append(f"-{args['n']}")
    return action + (f"  {' · '.join(bits)}" if bits else "")


def _run_git(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
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


def _inside_work_tree() -> bool:
    rc, out, _ = _run_git(["rev-parse", "--is-inside-work-tree"], timeout=10)
    return rc == 0 and out.strip().lower() == "true"


TOOL = Tool(
    "git",
    (
        "Read-only git inspection: status, diff, log, show. "
        "`status` shows working tree and branch. "
        "`diff` shows changes (use staged=true for the index). "
        "`log` lists recent commits. "
        "`show` displays a commit (default HEAD)."
    ),
    {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "diff", "log", "show"],
            },
            "path": {"type": "string", "description": "Limit diff/log to this path."},
            "staged": {"type": "boolean", "description": "Show staged diff (action=diff)."},
            "n": {"type": "integer", "description": "Number of log entries (action=log)."},
            "commit": {"type": "string", "description": "Commit ref (action=show, default HEAD)."},
        },
        "required": ["action"],
    },
    "auto",
    run,
    priority=35,
    summary=summary,
    parallel_safe=True,
)
