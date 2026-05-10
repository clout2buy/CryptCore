from __future__ import annotations

from core import runtime, ui

from .types import Tool


PROMPT = """
Use this tool to present a concrete implementation plan and gate execution
behind user approval. The user sees the plan in a styled panel and can approve
or reject it with feedback. Do not edit files or run risky commands until the
tool result says approved.

## When to Use

Use before substantial implementation work:

1. New features that require several coordinated changes.
2. Multi-file changes touching more than 2 or 3 files.
3. Refactors that change existing structure or behavior.
4. Architectural choices where the approach matters.
5. Risky or destructive operations: deletes, rewrites, migrations, schema
   changes, broad search/replace, or commands that are hard to undo.
6. Situations where you would otherwise ask the user to choose an approach.

## When NOT to Use

- Single-line fixes.
- Small, obvious single-file edits.
- Pure research or explanation tasks.
- Work where the user already provided exact implementation steps.
- Trivial edits the user clearly asked you to make now.

Do not over-plan. If the change is obvious and low risk, proceed directly.

## How to Write the Plan

- Start with one short paragraph stating what you will build and why.
- List concrete steps with file paths, function names, and expected changes.
- Call out assumptions, risks, and tradeoffs.
- End with how success will be verified.
- Use read-only tools to inspect before proposing.
- Do not include the title in the body. The title renders separately.

## After the User Responds

- approved: execute the plan, usually with a todos list.
- rejected with feedback: revise and call this tool again.
- rejected without feedback: ask one focused ask_user question or stop.

## Important

- This tool is for approval, not discussion.
- Do not use ask_user to ask "is this plan okay". Use this tool.
- The user has not seen the plan until this tool is called.
""".strip()


def run(args: dict) -> str:
    title = str(args.get("title", "")).strip() or "plan"
    plan = str(args.get("plan", "")).strip()
    if not plan:
        return "present_plan: plan is required"

    ui.plan_panel(title, plan)
    if not runtime.render_tools():
        return "approved. proceed with execution."
    if runtime.can_auto_approve_plan():
        ui.info("approval mode yolo-all - auto-approving plan")
        return "approved. proceed with execution."
    approved, inline_feedback = ui.confirm("approve this plan and proceed?")
    if approved:
        return "approved. proceed with execution."
    if inline_feedback:
        return f"rejected. user feedback: {inline_feedback}"

    feedback = ui.feedback_prompt()
    if not feedback:
        return "rejected. no feedback provided. stop or ask one focused question."
    return f"rejected. user feedback: {feedback}"


def summary(args: dict) -> str:
    return str(args.get("title", ""))


TOOL = Tool(
    name="present_plan",
    description=(
        "Present a concrete implementation plan and require user approval before "
        "substantial, risky, architectural, or multi-file work."
    ),
    schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short title under 60 characters.",
            },
            "plan": {
                "type": "string",
                "description": "Plan body in plain text or markdown.",
            },
        },
        "required": ["title", "plan"],
    },
    permission="auto",
    run=run,
    prompt=PROMPT,
    priority=90,
    summary=summary,
    available_in_subagent=False,
)
