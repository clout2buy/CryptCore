from __future__ import annotations

from core import runtime, skill_forge

from .fs import int_arg
from .types import Tool


PROMPT = """
Use this tool when repeated learned lessons should become a durable local
SKILL.md. Forged skills are project-local and should be used only for stable,
reusable workflows.
""".strip()


def run(args: dict) -> str:
    result = skill_forge.forge_skill(
        str(args.get("cwd") or runtime.cwd()),
        topic=str(args.get("topic") or ""),
        name=str(args.get("name") or ""),
        min_lessons=int_arg(args, "min_lessons", 2, 20),
    )
    return skill_forge.format_result(result)


def summary(args: dict) -> str:
    topic = str(args.get("topic") or args.get("name") or "learned workflow")
    return f"forge {topic[:80]}"


TOOL = Tool(
    "skill_forge",
    "Forge a project-local SKILL.md from learned lessons.",
    {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "name": {"type": "string"},
            "cwd": {"type": "string"},
            "min_lessons": {"type": "integer"},
        },
    },
    "ask",
    run,
    prompt=PROMPT,
    priority=86,
    summary=summary,
)
