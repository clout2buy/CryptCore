from __future__ import annotations

import re
import subprocess

from .fs import clip, root
from .types import Tool


_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def run(args: dict) -> str:
    action = str(args.get("action", "")).strip().lower()
    if action == "create":
        branch = _branch(args.get("branch"))
        start_point = str(args.get("start_point") or "").strip()
        cmd = ["switch", "-c", branch]
        if start_point:
            cmd.append(start_point)
    elif action == "switch":
        branch = _branch(args.get("branch"))
        cmd = ["switch", branch]
    elif action == "list":
        cmd = ["branch", "--list"]
    else:
        raise ValueError("action must be create, switch, or list")

    rc, out, err = _run_git(cmd)
    body = "\n".join(x.rstrip() for x in (out, err) if x.strip()).strip()
    if rc != 0:
        raise RuntimeError(f"git branch {action}: exit {rc}\n{body or '(no output)'}")
    return clip(body or f"branch {action} succeeded", 12000)


def _branch(raw) -> str:
    branch = str(raw or "").strip()
    if not branch:
        raise ValueError("branch is required")
    if branch.startswith("-") or ".." in branch or not _BRANCH_RE.match(branch):
        raise ValueError(f"unsafe branch name: {branch!r}")
    return branch


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
    action = str(args.get("action", ""))
    branch = str(args.get("branch", ""))
    return f"{action} {branch}".strip()


PROMPT = """
Use git_branch for intentional branch creation or switching. Inspect git
status first; if switching might collide with local changes, explain that
risk instead of forcing it.
""".strip()


TOOL = Tool(
    "git_branch",
    "Create, switch, or list Git branches. Create/switch require user approval.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "switch", "list"]},
            "branch": {"type": "string"},
            "start_point": {"type": "string"},
        },
        "required": ["action"],
    },
    "ask",
    run,
    prompt=PROMPT,
    priority=43,
    summary=summary,
    available_in_subagent=False,
)
