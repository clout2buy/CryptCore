from __future__ import annotations

from core import autonomy, runtime

from .fs import int_arg
from .types import Tool


PROMPT = """
Use this tool to inspect or run Crypt's safe autonomous learning cycle. The
cycle reflects on recent work, reviews due goals, updates lessons, and may
forge local skills from repeated patterns.
""".strip()


def run(args: dict) -> str:
    action = str(args.get("action") or "status").strip().lower()
    cwd = str(args.get("cwd") or runtime.cwd())
    limit = int_arg(args, "limit", 5, 50)
    if action == "status":
        return autonomy.format_cycles(cwd, limit=limit)
    if action == "run":
        cycle = autonomy.run_cycle(cwd, force_forge=bool(args.get("force_forge")), max_reflections=limit)
        lines = [
            f"{cycle.cycle_id}: reflected={cycle.reflected}, goals={cycle.goal_reviews}, lessons={cycle.lessons_added}",
        ]
        lines.extend(f"- {note}" for note in cycle.notes)
        return "\n".join(lines)
    raise ValueError("unknown autonomy action; use status or run")


def classify(args: dict) -> str | None:
    return "safe" if str(args.get("action") or "status").strip().lower() == "status" else None


TOOL = Tool(
    "autonomy",
    "Inspect or run Crypt's safe autonomous learning cycle.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "run"]},
            "cwd": {"type": "string"},
            "limit": {"type": "integer"},
            "force_forge": {"type": "boolean"},
        },
        "required": ["action"],
    },
    "ask",
    run,
    prompt=PROMPT,
    priority=82,
    classify=classify,
    parallel_safe=True,
)
