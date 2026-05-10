from __future__ import annotations

from core import runtime, ui

from .types import Tool


PROMPT = """
Use this tool to switch the workspace root mid-session. Every file tool
(read_file, edit_file, write_file, list_files, grep, open_file) and bash will
use the new path immediately, so paths in your subsequent calls should be
relative to the new root or absolute under it.

## When to Use

- The user names a project folder and asks you to work there
  (e.g., "work in D:\\my-project", "use ~/code/foo for this", "the project is
  at /Users/x/repo")
- The user provides a path at the start of a task as the working location
- You realize the active workspace is wrong for the task at hand

## When NOT to Use

- For a single read of a file outside the current workspace - bash with the
  absolute path is simpler.
- When the user only mentions a path in passing, not as a workspace directive.
- To navigate inside the current workspace - use relative paths instead.

## Behavior

- Validates the path exists and is a directory.
- Updates the live workspace root for the rest of the session.
- Does not persist across runs. The user controls the saved workspace via setup.
- Returns the resolved absolute path.
""".strip()


def run(args: dict) -> str:
    path = str(args.get("path", "")).strip()
    if not path:
        return "set_workspace: path is required"
    try:
        new = runtime.set_cwd(path)
    except Exception as e:
        return f"failed to set workspace: {type(e).__name__}: {e}"
    ui.workspace_changed(str(new))
    return f"workspace is now {new}"


def summary(args: dict) -> str:
    return str(args.get("path", ""))


TOOL = Tool(
    name="set_workspace",
    description=(
        "Switch the workspace root to a different directory. All file tools and "
        "bash use the new path immediately. Use when the user asks you to work "
        "in a specific folder."
    ),
    schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or user-relative path to a directory.",
            },
        },
        "required": ["path"],
    },
    permission="auto",
    run=run,
    prompt=PROMPT,
    priority=5,
    summary=summary,
    available_in_subagent=False,
)

