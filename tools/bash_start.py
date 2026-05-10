from __future__ import annotations

from core import background

from .bash_safety import classify as _classify_command, is_destructive
from .types import Tool


PROMPT = """
Use this for commands that may run longer than a quick foreground shell call:
installs, test suites, dev servers, watchers, builds, migrations, or any
command where blocking the agent loop would slow the workflow.

After starting a job, use bash_poll with the returned job_id to inspect output.
Use bash_kill only when the command is clearly stuck or the user asks.
""".strip()


def run(args: dict) -> str:
    command = str(args["command"]).strip()
    if not command:
        raise ValueError("command is required")
    job = background.start(command, description=str(args.get("description") or ""))
    return (
        f"started background job {job.id}\n"
        f"cwd: {job.cwd}\n"
        f"output: {job.output_path}\n"
        f"poll with bash_poll job_id={job.id}"
    )


def classify(args: dict) -> str | None:
    return _classify_command(str(args.get("command", "")))


def summary(args: dict) -> str:
    cmd = str(args.get("command", ""))
    reason = is_destructive(cmd)
    label = cmd[:120]
    return f"!{label} ({reason})" if reason else label


TOOL = Tool(
    "bash_start",
    "Start a shell command in the background and return a job id plus output log path.",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["command"],
    },
    "ask",
    run,
    prompt=PROMPT,
    priority=62,
    summary=summary,
    classify=classify,
)

