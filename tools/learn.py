from __future__ import annotations

from core import learning, runtime

from .fs import clip, int_arg
from .types import Tool


PROMPT = """
Use this tool for Crypt's structured learning store.

Use action=list or action=search to retrieve learned project/global lessons.
Use action=episodes to inspect prior task outcomes. Use action=add only for
explicit durable lessons, project conventions, recurring recovery patterns, or
workflow knowledge that should affect future turns.

Do not store secrets, credentials, private keys, raw logs, or transient details.
""".strip()


def run(args: dict) -> str:
    action = str(args.get("action") or "list").strip().lower()
    cwd = str(args.get("cwd") or runtime.cwd())
    limit = int_arg(args, "limit", 12, 50)
    if action == "list":
        return clip(learning.format_lessons(cwd, limit=limit), 12_000)
    if action == "search":
        query = str(args.get("query") or args.get("text") or "").strip()
        if not query:
            return "learn search requires query"
        return clip(
            learning.format_lessons(cwd, query=query, limit=limit)
            + "\n\n"
            + learning.format_episodes(cwd, query=query, limit=max(3, limit // 2)),
            16_000,
        )
    if action == "episodes":
        query = str(args.get("query") or args.get("text") or "").strip()
        return clip(learning.format_episodes(cwd, query=query, limit=limit), 12_000)
    if action == "add":
        text = str(args.get("text") or "").strip()
        scope = str(args.get("scope") or "project")
        lesson = learning.add_lesson(text, cwd=cwd, scope=scope, source="tool")
        return f"learned {lesson.lesson_id}: {lesson.text}"
    raise ValueError("unknown learn action; use list, search, episodes, or add")


def classify(args: dict) -> str | None:
    action = str(args.get("action") or "list").strip().lower()
    return "safe" if action in {"list", "search", "episodes"} else None


def summary(args: dict) -> str:
    action = str(args.get("action") or "list").strip().lower()
    if action == "search":
        return f"search {str(args.get('query') or args.get('text') or '')[:60]}"
    return action


TOOL = Tool(
    "learn",
    "Read, search, or add structured Crypt lessons and task episodes.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "search", "episodes", "add"]},
            "query": {"type": "string"},
            "text": {"type": "string"},
            "scope": {"type": "string", "enum": ["project", "global"]},
            "cwd": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["action"],
    },
    "ask",
    run,
    prompt=PROMPT,
    priority=84,
    summary=summary,
    classify=classify,
    parallel_safe=True,
)
