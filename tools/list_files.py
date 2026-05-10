from __future__ import annotations

from .fs import all_files, int_arg, rel, resolve
from .types import Tool


def run(args: dict) -> str:
    limit = int_arg(args, "limit", 200, 1000)
    out = []
    for path in all_files(resolve(args.get("path", "."))):
        out.append(rel(path))
        if len(out) >= limit:
            break
    return "\n".join(out) or "(no files)"


def summary(args: dict) -> str:
    return str(args.get("path", "."))


TOOL = Tool(
    "list_files",
    "List files under a workspace path, skipping caches and VCS dirs.",
    {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}},
    "auto",
    run,
    priority=10,
    summary=summary,
    parallel_safe=True,
)
