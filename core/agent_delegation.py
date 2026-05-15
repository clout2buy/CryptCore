"""Agent delegation decisions for Crypt."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import agent_profiles, intent_router, settings


CREATE_INTENTS = {"business", "code", "research", "browser", "desktop", "schedule", "external"}
LOCAL_INTENTS = {"conversation", "memory"}


@dataclass(frozen=True)
class DelegationDecision:
    action: str
    rationale: str
    confidence: float
    agent_id: str = ""
    agent_name: str = ""
    agent_type: str = ""
    route_role: str = ""
    provider: str = ""
    model: str = ""
    suggested_profile: dict[str, Any] = field(default_factory=dict)


def decide(
    cwd: str | Path,
    text: str,
    route: intent_router.IntentRoute | None = None,
) -> DelegationDecision:
    route = route or intent_router.route(text)
    profiles = [profile for profile in agent_profiles.list_profiles(cwd) if profile.status == "active"]
    best_profile, best_score = _best_profile(profiles, text, route)
    if best_profile and best_score >= 0.38:
        return DelegationDecision(
            action="use-agent",
            rationale=f"Existing specialist matches {route.intent} with score {best_score:.2f}.",
            confidence=min(0.95, 0.62 + best_score),
            agent_id=best_profile.id,
            agent_name=best_profile.name,
            agent_type=best_profile.agent_type,
            route_role=best_profile.route_role,
            provider=best_profile.provider,
            model=best_profile.model,
        )
    if _should_create(route, text):
        suggestion = _suggest_profile(text, route)
        return DelegationDecision(
            action="create-agent",
            rationale=f"No saved specialist fits this {route.intent} work yet.",
            confidence=0.82 if route.durable else 0.72,
            agent_name=suggestion["name"],
            agent_type=suggestion["agent_type"],
            route_role=agent_profiles.route_role_for_agent(suggestion["agent_type"]),
            provider=suggestion["provider"],
            model=suggestion["model"],
            suggested_profile=suggestion,
        )
    if best_profile and 0.25 <= best_score < 0.38:
        return DelegationDecision(
            action="update-agent",
            rationale=f"Closest specialist is {best_profile.name}, but its routing hints may need tuning.",
            confidence=0.56,
            agent_id=best_profile.id,
            agent_name=best_profile.name,
            agent_type=best_profile.agent_type,
            route_role=best_profile.route_role,
            provider=best_profile.provider,
            model=best_profile.model,
        )
    return DelegationDecision(
        action="local",
        rationale="Simple or conversational request; main Crypt can handle it directly.",
        confidence=0.7 if route.intent in LOCAL_INTENTS else 0.52,
        route_role=route.route_role,
    )


def apply_decision(cwd: str | Path, decision: DelegationDecision) -> agent_profiles.AgentProfile | None:
    if decision.action != "create-agent" or not decision.suggested_profile:
        return None
    existing = agent_profiles.list_profiles(cwd)
    if any(profile.name.lower() == str(decision.suggested_profile.get("name", "")).lower() for profile in existing):
        return None
    return agent_profiles.create_profile(
        cwd,
        name=str(decision.suggested_profile.get("name") or decision.agent_name),
        purpose=str(decision.suggested_profile.get("purpose") or "Handle delegated work for Crypt."),
        agent_type=str(decision.suggested_profile.get("agent_type") or decision.agent_type),
        provider=str(decision.suggested_profile.get("provider") or settings.provider_default({})),
        model=str(decision.suggested_profile.get("model") or ""),
        tools=list(decision.suggested_profile.get("tools") or []),
        memory_scope=str(decision.suggested_profile.get("memory_scope") or "workspace"),
        persona_constraints=list(decision.suggested_profile.get("persona_constraints") or []),
        routing_hints=list(decision.suggested_profile.get("routing_hints") or []),
    )


def prompt_section(cwd: str | Path, text: str) -> str:
    decision = decide(cwd, text)
    lines = ["# Agent Delegation Brain"]
    lines.append(f"- Decision: {decision.action}; confidence={decision.confidence:.2f}; route={decision.route_role or decision.agent_type or 'local'}.")
    lines.append(f"- Rationale: {decision.rationale}")
    if decision.agent_name:
        lines.append(f"- Agent: {decision.agent_name} ({decision.agent_type})")
    if decision.suggested_profile:
        lines.append(f"- Suggested purpose: {decision.suggested_profile.get('purpose', '')}")
    return "\n".join(lines)


def snapshot(cwd: str | Path, text: str = "") -> dict[str, Any]:
    decision = decide(cwd, text or "general help")
    return {"decision": asdict(decision), "profiles": [profile.to_dict() for profile in agent_profiles.list_profiles(cwd)]}


def _best_profile(
    profiles: list[agent_profiles.AgentProfile],
    text: str,
    route: intent_router.IntentRoute,
) -> tuple[agent_profiles.AgentProfile | None, float]:
    query_tokens = _tokens(f"{text} {route.intent} {route.rationale}")
    best: tuple[agent_profiles.AgentProfile | None, float] = (None, 0.0)
    for profile in profiles:
        haystack = " ".join(
            [
                profile.name,
                profile.purpose,
                profile.agent_type,
                profile.route_role,
                " ".join(profile.tools or []),
                " ".join(profile.routing_hints or []),
            ]
        )
        profile_tokens = _tokens(haystack)
        overlap = len(query_tokens & profile_tokens)
        score = overlap / max(4, len(query_tokens))
        if profile.route_role == route.route_role:
            score += 0.14
        if route.intent in profile_tokens:
            score += 0.12
        if score > best[1]:
            best = (profile, score)
    return best


def _should_create(route: intent_router.IntentRoute, text: str) -> bool:
    lower = text.lower()
    if route.intent in LOCAL_INTENTS:
        return False
    if "agent" in lower or "specialist" in lower:
        return True
    return bool(route.durable and route.intent in CREATE_INTENTS)


def _suggest_profile(text: str, route: intent_router.IntentRoute) -> dict[str, Any]:
    provider = settings.PROVIDER_CRYPT if settings.PROVIDER_CRYPT in settings.PROVIDERS else settings.provider_default({})
    model = "gpt-5.3-codex-spark" if route.route_role in {"fast", "planner"} else "gpt-5.5"
    intent = route.intent
    if intent == "business":
        return _profile("Growth Operator", "Find customers, draft launch assets, monitor revenue, and keep business work moving.", "worker", provider, model, ["web_search", "write_file"], text)
    if intent in {"code", "file"}:
        return _profile("Code Builder", "Inspect code, implement scoped patches, run checks, and summarize diffs.", "worker", provider, model, ["read_file", "edit_file", "shell"], text)
    if intent in {"research", "browser"}:
        return _profile("Research Scout", "Search, read, extract, compare, and return sourced findings.", "explorer", provider, model, ["web_search", "fetch_url"], text)
    if intent == "desktop":
        return _profile("Desktop Operator", "Operate visible desktop workflows with narration and approval gates.", "worker", provider, model, ["desktop", "screenshot"], text)
    if intent == "schedule":
        return _profile("Ops Monitor", "Track recurring checks, schedules, monitors, and follow-up work.", "planner", provider, model, ["scheduler", "monitors"], text)
    return _profile("Crypt Specialist", "Handle repeated delegated work for this request type.", "worker", provider, model, [], text)


def _profile(name: str, purpose: str, agent_type: str, provider: str, model: str, tools: list[str], text: str) -> dict[str, Any]:
    return {
        "name": name,
        "purpose": purpose,
        "agent_type": agent_type,
        "provider": provider,
        "model": model,
        "tools": tools,
        "memory_scope": "workspace",
        "persona_constraints": ["Be direct, concise, and practical."],
        "routing_hints": [_one_line(text, 140)],
    }


def _tokens(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9][a-z0-9_.+-]{2,}", str(value or "").lower())}


def _one_line(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
