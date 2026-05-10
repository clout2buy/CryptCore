from __future__ import annotations

from core.agents import tasks

from .types import Tool


def run(args: dict) -> str:
    task_id = str(args["task_id"]).strip()
    tail = args.get("tail")
    task = tasks.require(task_id)
    output = tasks.format_task(task, tail=int(tail) if tail else None)
    if args.get("include_diff"):
        max_chars = int(args.get("diff_chars") or 12000)
        output += "\n\n" + tasks.worktree_diff(task_id, max_chars=max_chars)
    return output


def summary(args: dict) -> str:
    return str(args.get("task_id", ""))


TOOL = Tool(
    "agent_output",
    "Inspect a Crypt agent task's current status and output.",
    {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "tail": {"type": "integer", "description": "Optional number of output lines to return."},
            "include_diff": {
                "type": "boolean",
                "description": "When true, include changed files and git diff for an isolated worktree task.",
            },
            "diff_chars": {
                "type": "integer",
                "description": "Maximum number of diff characters to include when include_diff is true.",
            },
        },
        "required": ["task_id"],
    },
    "auto",
    run,
    priority=113,
    summary=summary,
    available_in_subagent=False,
    parallel_safe=True,
)
