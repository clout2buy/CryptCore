from __future__ import annotations

from core import background

from .types import Tool


def run(args: dict) -> str:
    job_id = str(args["job_id"]).strip()
    if not job_id:
        raise ValueError("job_id is required")
    return background.kill(job_id)


def summary(args: dict) -> str:
    return str(args.get("job_id", ""))


TOOL = Tool(
    "bash_kill",
    "Stop a running background shell job by job_id.",
    {
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
    },
    "ask",
    run,
    priority=64,
    summary=summary,
)

