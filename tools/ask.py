from __future__ import annotations

from core import ui

from .types import Tool


PROMPT = """
Use this tool when you need a real decision from the user during execution.
Ask multiple-choice when the answer is a choice. Ask free-form by omitting
options when you need open input.

## When to Use

1. Multiple valid approaches exist and the user's preference changes the work.
2. A required input is missing and cannot be reasonably inferred.
3. The user's request has conflicting signals that block progress.
4. The choice is reversible but annoying: naming, scope, defaults, or UX.

## When NOT to Use

- Trivial defaults you can pick yourself. Pick and proceed.
- Plan approval. Use present_plan instead.
- After making a decision yourself. Do not second-guess.
- To stall when the next step is obvious. Do the work.
- Approach-level decisions on substantial work. Use present_plan so the user
  sees the full context, not a bare question.

## Format

- Use 2 to 5 short, distinct options for choice questions.
- If you recommend an option, put it first and add "(Recommended)".
- Omit options for open-ended answers like names, paths, or numbers.
- Keep option labels under about 60 characters.

## Examples

GOOD:
- question: "Which database backend?"
  options: [
    "SQLite (Recommended) - single file, zero setup",
    "Postgres - production-grade",
    "DuckDB - analytics-first"
  ]

GOOD:
- question: "What should the new module be named?"
  options: []

BAD:
- "Is this plan okay?" Use present_plan.
- "Tabs or spaces?" Match the existing file.
""".strip()


def run(args: dict) -> str:
    question = str(args.get("question", "")).strip()
    options = [str(o) for o in (args.get("options") or [])]
    if not question:
        return "ask_user: question is required"
    return ui.ask_choice(question, options)


def summary(args: dict) -> str:
    return str(args.get("question", ""))


TOOL = Tool(
    name="ask_user",
    description=(
        "Ask the user a multiple-choice or free-form question mid-task and wait "
        "for the answer. Use only for decisions that need the user."
    ),
    schema={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question"],
    },
    permission="auto",
    run=run,
    prompt=PROMPT,
    priority=100,
    summary=summary,
    available_in_subagent=False,
)
