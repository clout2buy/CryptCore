from __future__ import annotations

from core import background

from .fs import int_arg
from .types import Tool


def run(args: dict) -> str:
    job_id = str(args.get("job_id", "")).strip()
    if not job_id:
        jobs = background.list_jobs()
        if not jobs:
            return "(no background jobs)"
        return "\n".join(
            f"{j.id}: {background.status(j)} - {j.command} - {j.output_path}"
            for j in jobs
        )
    return background.poll(job_id, int_arg(args, "tail_lines", 80, 500))


def summary(args: dict) -> str:
    return str(args.get("job_id") or "list")


TOOL = Tool(
    "bash_poll",
    "Poll a background shell job, or list jobs when job_id is omitted.",
    {
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "tail_lines": {"type": "integer"},
        },
    },
    "auto",
    run,
    priority=63,
    summary=summary,
    parallel_safe=True,
)
