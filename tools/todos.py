from __future__ import annotations

from core import ui

from .types import Tool


PROMPT = """
Use this tool to create and manage a structured task list for the current
session. The list is shown to the user as a panel above their input prompt
and updated live as you mark items off.

## When to Use

Use proactively for:

1. Multi-step tasks with 3 or more distinct steps.
2. Non-trivial implementation work requiring several operations.
3. Explicit user requests for a todo list.
4. User requests that include multiple tasks.
5. New instructions that change scope or add requirements.

## When NOT to Use

- A single, straightforward task.
- Trivial work where tracking adds no value.
- Pure conversation, Q&A, or explanation.
- Anything that is fewer than 3 simple steps.

## When to Call (frequency matters)

Call `todos` ONLY when status meaningfully changes. Specifically:

1. ONCE at the start of a multi-step task — to seed the list.
2. ONCE when a task transitions: pending → doing, or doing → done.
3. ONCE when discovering a new task to add or removing one.

Do NOT call `todos` after every tool action — that floods the display
with redundant updates. The user sees the panel once per turn, above
their next prompt. Save your tool calls for actual state changes.

## Demo / screenshot requests

When the user asks to test or screenshot the todo UI:

1. Create a small harmless list with 3-6 concrete items.
2. Say one short setup sentence before the first todo update.
3. Seed the list with the first item `doing` and the rest `pending`.
4. Advance exactly one visible step per `todos` call. Do not jump straight to all done.
5. Keep assistant narration minimal; the panel is the main output.
6. Do not read huge files or run unrelated commands just to make progress.
7. End with one concise completion sentence.

## Rules

1. Pass the full list every call. The list is replaced, not merged.
2. Valid statuses: pending, doing, done.
3. Exactly one item should be doing while work is active.
4. Only mark done when the item is fully complete.
5. If blocked, keep the item doing and add a pending item for the blocker.
6. Remove items that turn out to be irrelevant.

## Examples

GOOD:
User: "Add a dark mode toggle and run the tests"
→ ONE call to seed:
  [{"text": "Add toggle component", "status": "doing"},
   {"text": "Wire theme state",     "status": "pending"},
   {"text": "Add CSS variables",    "status": "pending"},
   {"text": "Run tests",            "status": "pending"}]
→ After component is built, ONE call to advance:
  [{"text": "Add toggle component", "status": "done"},
   {"text": "Wire theme state",     "status": "doing"},
   ...]

BAD:
- Calling `todos` after every read_file or edit_file inside a single task.
- Re-sending the unchanged list "just in case".
""".strip()


_TODOS: list[dict] = []


def clear() -> None:
    _TODOS.clear()
    ui.todos_panel(_TODOS)


def get_todos() -> list[dict]:
    return list(_TODOS)


def complete_all() -> bool:
    if not _TODOS or all(t.get("status") == "done" for t in _TODOS):
        return False
    for item in _TODOS:
        item["status"] = "done"
    ui.todos_panel(_TODOS)
    return True


def run(args: dict) -> str:
    items = args.get("todos") or []
    cleaned: list[dict] = []
    doing = 0

    for item in items:
        text = str(item.get("text", "")).strip()
        status = str(item.get("status", "pending")).strip().lower()
        if status not in ("pending", "doing", "done"):
            status = "pending"
        if status == "doing":
            doing += 1
        if text:
            cleaned.append({"text": text, "status": status})

    _TODOS.clear()
    _TODOS.extend(cleaned)
    ui.todos_panel(_TODOS)

    done = sum(1 for t in _TODOS if t["status"] == "done")
    doing_item = next((t for t in _TODOS if t["status"] == "doing"), None)
    note = "  ⚠ more than one item doing" if doing > 1 else ""
    if doing_item:
        return f"todos {done}/{len(_TODOS)} done · doing: {doing_item['text']}{note}"
    return f"todos {done}/{len(_TODOS)} done{note}"


def before_prompt() -> None:
    if _TODOS and any(t.get("status") != "done" for t in _TODOS):
        ui.todos_panel(_TODOS)


def summary(args: dict) -> str:
    items = args.get("todos") or []
    return f"{len(items)} item{'s' if len(items) != 1 else ''}"


TOOL = Tool(
    name="todos",
    description=(
        "Track multi-step work as a visible checklist. Pass the full list every "
        "call. Statuses: pending, doing, done. Keep exactly one item doing."
    ),
    schema={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "doing", "done"],
                        },
                    },
                    "required": ["text", "status"],
                },
            },
        },
        "required": ["todos"],
    },
    permission="auto",
    run=run,
    prompt=PROMPT,
    priority=80,
    summary=summary,
    before_prompt=before_prompt,
    reset=clear,
    quiet=True,
    available_in_subagent=False,
)
