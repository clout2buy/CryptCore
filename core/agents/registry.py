from __future__ import annotations

from .contracts import AgentDefinition
from . import prompts, toolsets


_AGENTS: dict[str, AgentDefinition] = {
    "explorer": AgentDefinition(
        name="explorer",
        description="Read-only codebase investigation with compact evidence.",
        system_prompt=prompts.EXPLORER,
        allowed_tools=toolsets.READ_ONLY_TOOLS,
        output_contract="Report facts only; include paths/lines where possible.",
        ui_label="explorer",
    ),
    "planner": AgentDefinition(
        name="planner",
        description="Read-only implementation planning from repo evidence.",
        system_prompt=prompts.PLANNER,
        allowed_tools=toolsets.READ_ONLY_TOOLS,
        output_contract="Return files, approach, risks, and test plan.",
        ui_label="planner",
    ),
    "worker": AgentDefinition(
        name="worker",
        description="Scoped implementation worker with write ownership.",
        system_prompt=prompts.WORKER,
        allowed_tools=toolsets.WORKER_TOOLS,
        output_contract="Return changed files, key decisions, and verification.",
        read_only=False,
        requires_write_paths=True,
        ui_label="worker",
        default_mode="background",
    ),
    "verifier": AgentDefinition(
        name="verifier",
        description="Independent adversarial verifier.",
        system_prompt=prompts.VERIFIER,
        allowed_tools=toolsets.READ_ONLY_TOOLS,
        output_contract="Must include VERDICT: PASS, FAIL, or PARTIAL.",
        ui_label="verifier",
    ),
    "ui_reviewer": AgentDefinition(
        name="ui_reviewer",
        description="Terminal UI and transcript reviewer.",
        system_prompt=prompts.UI_REVIEWER,
        allowed_tools=toolsets.READ_ONLY_TOOLS,
        output_contract="Return UI findings and affected surfaces.",
        ui_label="ui",
    ),
    "release_reviewer": AgentDefinition(
        name="release_reviewer",
        description="Release readiness reviewer.",
        system_prompt=prompts.RELEASE_REVIEWER,
        allowed_tools=toolsets.READ_ONLY_TOOLS,
        output_contract="Return blockers, residual risks, and readiness verdict.",
        ui_label="release",
    ),
}


def get_agent(name: str | None) -> AgentDefinition:
    key = str(name or "explorer").strip() or "explorer"
    if key not in _AGENTS:
        raise KeyError(f"unknown agent_type {key!r}; choose one of {', '.join(sorted(_AGENTS))}")
    return _AGENTS[key]


def list_agents() -> list[AgentDefinition]:
    return list(_AGENTS.values())


def agent_names() -> list[str]:
    return sorted(_AGENTS)


def build_prompt(
    definition: AgentDefinition,
    *,
    prompt: str,
    context: str | None = None,
    scope: str = "",
    write_paths: list[str] | None = None,
) -> str:
    parts = [
        definition.system_prompt,
        f"Output contract: {definition.output_contract}",
    ]
    if scope:
        parts.append(f"Scope: {scope}")
    if write_paths:
        parts.append("Write paths:\n" + "\n".join(f"- {p}" for p in write_paths))
    if context and context.strip():
        parts.append("<parent_context>\n" + context.strip() + "\n</parent_context>")
    parts.append("<task>\n" + str(prompt).strip() + "\n</task>")
    return "\n\n".join(parts)
