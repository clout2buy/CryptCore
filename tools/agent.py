from __future__ import annotations

import uuid

from core import runtime, ui
from core import settings, worktrees
from core.agents import registry as agent_registry
from core.agents import tasks as agent_tasks

from .types import Tool


PROMPT = """
Use this tool to run a focused typed subagent with a fresh, isolated context.
The subagent receives only your prompt/context and returns a compact result.
Its intermediate file reads and tool calls do not enter your context.

## When to Use

1. Open-ended codebase research that would spam your context with file reads.
2. Large searches where you need a compact report.
3. Independent investigations that can run without this conversation history.
4. Summarizing many files into a short answer.
5. Getting a second read before a risky design decision.
6. Scoped worker implementation when write_paths are explicit.
7. Independent verification after a risky or broad change.
8. Broad repo audits, upgrade planning, architecture review, or "where are we at" requests. Use this proactively; the user should not have to say "use agents".

## When NOT to Use

- Tasks you can finish in a few tool calls yourself.
- Trivial lookups where read_file or grep is faster.
- Work requiring this conversation's hidden context.
- Step-by-step supervised work.
- Delegating synthesis you should do yourself.
- Worker edits without a narrow write_paths ownership boundary.

## Agent Types

- explorer: read-only repo investigation.
- planner: read-only implementation planning.
- worker: scoped implementation; requires write_paths.
- verifier: independent check; final answer must include VERDICT.
- ui_reviewer: terminal UI/transcript review.
- release_reviewer: release readiness review.

## Writing the Prompt

Brief the subagent like a smart colleague who just walked in:

- State the goal and why it matters.
- Include what you already know or ruled out.
- Include exact paths, symbols, commands, or constraints when you have them.
- Say how short the report should be when you need brevity.
- For investigations, ask the question. Do not prescribe brittle steps.

Never write "based on your findings, fix the bug". That delegates
understanding. Ask for the evidence, then you decide what to do.
""".strip()


def run(args: dict) -> str:
    description = str(args.get("description", "subagent")).strip() or "subagent"
    prompt = str(args.get("prompt", "")).strip()
    if not prompt:
        return "spawn_agent: prompt is required"
    context = str(args.get("context", "")).strip() or None
    agent_type = str(args.get("agent_type") or "explorer").strip() or "explorer"
    name = str(args.get("name") or description).strip() or description
    mode = str(args.get("mode") or "sync").strip().lower()
    scope = str(args.get("scope") or "").strip()
    isolation = str(args.get("isolation") or "shared").strip().lower()
    write_paths = args.get("write_paths") or []
    if not isinstance(write_paths, list):
        return "spawn_agent: write_paths must be an array of strings"
    write_paths = [str(item).strip() for item in write_paths if str(item).strip()]
    if mode not in {"sync", "background"}:
        return "spawn_agent: mode must be sync or background"
    if isolation not in {"shared", "worktree"}:
        return "spawn_agent: isolation must be shared or worktree"
    try:
        definition = agent_registry.get_agent(agent_type)
    except KeyError as exc:
        return f"spawn_agent: {exc}"
    if definition.requires_write_paths and not write_paths:
        return "spawn_agent: worker agents require non-empty write_paths"
    worktree_path = ""
    if isolation == "worktree":
        try:
            if worktrees.is_dirty(runtime.cwd()):
                return (
                    "spawn_agent: worktree isolation requires a clean git tree; "
                    "commit, stash, or use shared isolation so the agent sees current changes"
                )
        except Exception as exc:
            return f"spawn_agent: worktree isolation failed: {type(exc).__name__}: {exc}"
        branch = f"codex/agent-{uuid.uuid4().hex[:8]}"
        path = settings.APP_DIR / "worktrees" / branch.replace("/", "-")
        try:
            worktree_path = str(worktrees.create(
                runtime.cwd(),
                worktrees.WorktreeSpec(branch=branch, path=path),
            ))
        except Exception as exc:
            return f"spawn_agent: worktree isolation failed: {type(exc).__name__}: {exc}"

    render = runtime.render_tools()
    if render:
        ui.subagent_start(f"{definition.ui_label}: {description}")
    background = mode == "background"
    task = agent_tasks.start_agent_task(
        definition=definition,
        name=name,
        prompt=prompt if not scope else f"Scope: {scope}\n\n{prompt}",
        context=context,
        scope=scope,
        write_paths=write_paths,
        isolation=isolation,
        worktree_path=worktree_path,
        runner=runtime.run_subagent,
        background=background,
    )
    if background:
        if render:
            ui.subagent_end(True, f"{description} ({task.id} background)")
        return (
            f"started {definition.name} agent {task.id}\n"
            f"name: {task.name}\n"
            f"status: {task.status.value}\n"
            f"inspect with agent_output task_id={task.id}"
        )

    output = task.result or task.error
    ok = task.status.value == "completed" and not output.startswith("spawn_agent unavailable")
    if render:
        ui.subagent_end(ok, description)
    return output or "(no output)"


def summary(args: dict) -> str:
    agent_type = str(args.get("agent_type") or "explorer")
    desc = str(args.get("description", ""))
    mode = str(args.get("mode") or "sync")
    return f"{agent_type}/{mode} {desc}".strip()


TOOL = Tool(
    name="spawn_agent",
    description=(
        "Run a typed subagent with fresh context. Supports explorer, planner, "
        "worker, verifier, ui_reviewer, and release_reviewer roles."
    ),
    schema={
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Short user-facing label under 60 characters.",
            },
            "prompt": {
                "type": "string",
                "description": "Self-contained briefing with scope and expected report.",
            },
            "context": {
                "type": "string",
                "description": (
                    "Optional excerpts already gathered by the parent. Plain "
                    "text; cite paths inline."
                ),
            },
            "agent_type": {
                "type": "string",
                "enum": ["explorer", "planner", "worker", "verifier", "ui_reviewer", "release_reviewer"],
                "description": "Typed agent role. Defaults to explorer.",
            },
            "name": {
                "type": "string",
                "description": "Short task name for the operations dock.",
            },
            "mode": {
                "type": "string",
                "enum": ["sync", "background"],
                "description": "sync waits for output; background returns a task id.",
            },
            "scope": {
                "type": "string",
                "description": "Responsibility boundary for the task.",
            },
            "write_paths": {
                "type": "array",
                "description": "Required for worker agents; paths the worker may edit.",
                "items": {"type": "string"},
            },
            "isolation": {
                "type": "string",
                "enum": ["shared", "worktree"],
                "description": "Execution isolation. shared is enabled; worktree is scaffolded.",
            },
        },
        "required": ["description", "prompt"],
    },
    permission="auto",
    run=run,
    prompt=PROMPT,
    priority=110,
    summary=summary,
    available_in_subagent=False,
)
