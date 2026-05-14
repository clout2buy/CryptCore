from __future__ import annotations

from core import goals, runtime

from .fs import int_arg
from .types import Tool


PROMPT = """
Use this tool to manage durable Crypt goals. Goals are long-lived objectives
that should shape future sessions, such as building a product, improving a
repo, monitoring a business, or preparing launches.

Use list for context. Use add/update only when the user explicitly asks for a
durable objective or the task clearly requires persistent tracking.
""".strip()


def run(args: dict) -> str:
    action = str(args.get("action") or "list").strip().lower()
    cwd = str(args.get("workspace") or runtime.cwd())
    if action == "list":
        return goals.format_goals(cwd, include_all=bool(args.get("include_all")))
    if action == "add":
        goal = goals.add_goal(
            str(args.get("title") or ""),
            description=str(args.get("description") or ""),
            workspace=cwd if args.get("project_scope", True) else None,
            success_metric=str(args.get("success_metric") or ""),
            cadence=str(args.get("cadence") or ""),
            priority=int_arg(args, "priority", 3, 5),
            tags=[str(tag) for tag in args.get("tags", [])] if isinstance(args.get("tags"), list) else [],
        )
        return f"added {goal.goal_id}: {goal.title}"
    if action == "update":
        goal = goals.update_goal(
            str(args.get("goal_id") or ""),
            status=args.get("status"),
            last_result=args.get("last_result"),
            priority=args.get("priority"),
        )
        return f"updated {goal.goal_id}: {goal.status}"
    raise ValueError("unknown goals action; use list, add, or update")


def classify(args: dict) -> str | None:
    action = str(args.get("action") or "list").strip().lower()
    return "safe" if action == "list" else None


def summary(args: dict) -> str:
    action = str(args.get("action") or "list").strip().lower()
    if action == "add":
        return f"add {str(args.get('title') or '')[:60]}"
    if action == "update":
        return f"update {str(args.get('goal_id') or '')}"
    return "list"


TOOL = Tool(
    "goals",
    "List, add, or update durable Crypt goals.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "add", "update"]},
            "goal_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "success_metric": {"type": "string"},
            "cadence": {"type": "string"},
            "priority": {"type": "integer"},
            "status": {"type": "string", "enum": ["active", "paused", "completed", "cancelled"]},
            "last_result": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "workspace": {"type": "string"},
            "project_scope": {"type": "boolean"},
            "include_all": {"type": "boolean"},
        },
        "required": ["action"],
    },
    "ask",
    run,
    prompt=PROMPT,
    priority=83,
    summary=summary,
    classify=classify,
    parallel_safe=True,
)
