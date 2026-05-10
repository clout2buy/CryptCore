from __future__ import annotations

import subprocess

from .fs import clip, root
from .types import Tool


def run(args: dict) -> str:
    message = str(args.get("message", "")).strip()
    if not message:
        raise ValueError("commit message is required")

    cmd = ["commit", "-m", message]
    if args.get("allow_empty"):
        cmd.append("--allow-empty")

    rc, out, err = _run_git(cmd)
    body = "\n".join(x.rstrip() for x in (out, err) if x.strip()).strip()
    if rc != 0:
        raise RuntimeError(f"git commit: exit {rc}\n{body or '(no output)'}")
    return clip(body or "committed", 12000)


def _run_git(cmd: list[str], timeout: int = 90) -> tuple[int, str, str]:
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
    msg = str(args.get("message", ""))
    return msg if len(msg) <= 80 else msg[:79] + "."


PROMPT = """
Use git_commit only after inspecting staged diff. Do not amend commits unless
the user explicitly asks. Do not commit unrelated work you did not make unless
the user asked for a broad commit and the staged diff matches that request.
""".strip()


TOOL = Tool(
    "git_commit",
    "Create a Git commit from the staged index. Requires user approval.",
    {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "allow_empty": {"type": "boolean"},
        },
        "required": ["message"],
    },
    "ask",
    run,
    prompt=PROMPT,
    priority=45,
    summary=summary,
    available_in_subagent=False,
)
