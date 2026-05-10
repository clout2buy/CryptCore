from __future__ import annotations

from core import runtime
from core.agents import tasks

from .types import Tool


def run(args: dict) -> str:
    task_id = str(args["task_id"]).strip()
    message = str(args["message"]).strip()
    if not message:
        raise ValueError("message is required")
    action = str(args.get("action") or "queue").strip().lower()
    if action == "continue":
        task = tasks.continue_agent_task(task_id, message, runner=runtime.run_subagent, background=True)
        return f"started continuation agent {task.id} for {task_id}"
    return tasks.queue_message(task_id, message)


def summary(args: dict) -> str:
    return str(args.get("task_id", ""))


TOOL = Tool(
    "send_agent_message",
    "Record a note for an agent task, or start a background continuation for a completed task.",
    {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "message": {"type": "string"},
            "action": {
                "type": "string",
                "enum": ["queue", "continue"],
                "description": "queue records the note; continue starts a follow-up task.",
            },
        },
        "required": ["task_id", "message"],
    },
    "auto",
    run,
    priority=114,
    summary=summary,
    available_in_subagent=False,
)
