from __future__ import annotations

from core.agents import tasks

from .types import Tool


def run(args: dict) -> str:
    return tasks.request_stop(str(args["task_id"]).strip(), str(args.get("reason") or ""))


def summary(args: dict) -> str:
    return str(args.get("task_id", ""))


TOOL = Tool(
    "stop_agent",
    "Request cancellation for a Crypt background agent task.",
    {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["task_id"],
    },
    "auto",
    run,
    priority=115,
    summary=summary,
    available_in_subagent=False,
)
