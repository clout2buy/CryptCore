from __future__ import annotations

from core.agents import tasks

from .types import Tool


def run(args: dict) -> str:
    status = str(args.get("status") or "").strip() or None
    items = tasks.list_tasks(status=status)
    if not items:
        return "(no agent tasks)"
    return "\n".join(tasks.format_task(task).splitlines()[0] for task in items)


def summary(args: dict) -> str:
    return str(args.get("status") or "all")


TOOL = Tool(
    "list_agents",
    "List active and recent Crypt agent tasks.",
    {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["queued", "running", "completed", "failed", "cancel_requested", "cancelled"],
            },
        },
    },
    "auto",
    run,
    priority=112,
    summary=summary,
    available_in_subagent=False,
    parallel_safe=True,
)
