from __future__ import annotations

from core.agents import tasks

from .types import Tool


def run(args: dict) -> str:
    task_id = str(args["task_id"]).strip()
    actions: list[str] = []
    if args.get("cleanup_worktree", True):
        actions.append(tasks.cleanup_worktree(task_id, force=bool(args.get("force"))))
    if args.get("forget"):
        actions.append(tasks.forget(task_id))
    return "\n".join(actions) if actions else "no cleanup action requested"


def summary(args: dict) -> str:
    return str(args.get("task_id", ""))


def classify(args: dict) -> str | None:
    return "danger" if args.get("force") else "safe"


TOOL = Tool(
    "cleanup_agent",
    "Clean up a finished Crypt agent task, including its isolated worktree.",
    {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "cleanup_worktree": {
                "type": "boolean",
                "description": "Remove the isolated git worktree when the task has one.",
            },
            "force": {
                "type": "boolean",
                "description": "Pass --force to git worktree remove for dirty finished worktrees.",
            },
            "forget": {
                "type": "boolean",
                "description": "Forget the finished task record after cleanup.",
            },
        },
        "required": ["task_id"],
    },
    "auto",
    run,
    priority=116,
    summary=summary,
    classify=classify,
    available_in_subagent=False,
)
