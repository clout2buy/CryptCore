from __future__ import annotations

from core import reflection, runtime

from .fs import int_arg
from .types import Tool


PROMPT = """
Use this tool to inspect or run Crypt's self-reflection pass over recent task
episodes. Reflection summarizes what worked, what failed, and what should be
done differently next time.
""".strip()


def run(args: dict) -> str:
    action = str(args.get("action") or "list").strip().lower()
    cwd = str(args.get("cwd") or runtime.cwd())
    limit = int_arg(args, "limit", 5, 50)
    if action == "list":
        return reflection.format_reflections(cwd, limit=limit)
    if action == "run":
        created = reflection.reflect_recent(cwd, limit=limit)
        if not created:
            return "no new episodes to reflect on"
        return "\n".join(f"{item.reflection_id}: {item.summary}" for item in created)
    raise ValueError("unknown reflect action; use list or run")


def classify(args: dict) -> str | None:
    return "safe" if str(args.get("action") or "list").strip().lower() == "list" else None


TOOL = Tool(
    "reflect",
    "List or run self-reflection over recent Crypt task episodes.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "run"]},
            "cwd": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["action"],
    },
    "ask",
    run,
    prompt=PROMPT,
    priority=84,
    classify=classify,
    parallel_safe=True,
)
