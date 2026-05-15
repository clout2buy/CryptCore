"""Persistent user-defined agent profiles for Crypt."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import settings
from .agents import registry


AGENT_STORE_DIR = ".crypt"
AGENT_STORE_FILE = "agents.json"

ROUTE_BY_AGENT_TYPE = {
    "explorer": "planner",
    "planner": "planner",
    "worker": "builder",
    "verifier": "reviewer",
    "ui_reviewer": "reviewer",
    "release_reviewer": "reviewer",
}


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    purpose: str
    agent_type: str
    provider: str
    model: str
    route_role: str
    status: str
    created_at: str
    updated_at: str
    schema_version: int = 2
    tools: list[str] | None = None
    memory_scope: str = "workspace"
    persona_constraints: list[str] | None = None
    routing_hints: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tools"] = list(self.tools or [])
        data["persona_constraints"] = list(self.persona_constraints or [])
        data["routing_hints"] = list(self.routing_hints or [])
        return data


def route_role_for_agent(agent_type: str) -> str:
    return ROUTE_BY_AGENT_TYPE.get(agent_type, "fallback")


def store_path(cwd: str | Path) -> Path:
    return Path(cwd) / AGENT_STORE_DIR / AGENT_STORE_FILE


def list_profiles(cwd: str | Path) -> list[AgentProfile]:
    raw = _read_store(store_path(cwd))
    profiles: list[AgentProfile] = []
    for item in raw:
        try:
            profiles.append(_profile_from_raw(item))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(profiles, key=lambda profile: profile.updated_at, reverse=True)


def get_profile(cwd: str | Path, agent_id: str) -> AgentProfile | None:
    for profile in list_profiles(cwd):
        if profile.id == agent_id:
            return profile
    return None


def create_profile(
    cwd: str | Path,
    *,
    name: str,
    purpose: str,
    agent_type: str,
    provider: str,
    model: str,
    tools: list[str] | None = None,
    memory_scope: str = "workspace",
    persona_constraints: list[str] | None = None,
    routing_hints: list[str] | None = None,
) -> AgentProfile:
    agent_type = _clean_agent_type(agent_type)
    default_provider = settings.provider_default({})
    provider = provider if provider in settings.PROVIDERS else default_provider
    model = (model or "").strip() or settings.model_default(provider, {})
    now = _now()
    profile = AgentProfile(
        id=_profile_id(name),
        name=_clean_text(name, fallback="Crypt Agent", max_len=80),
        purpose=_clean_text(purpose, fallback="Handle delegated work for Crypt.", max_len=600),
        agent_type=agent_type,
        provider=provider,
        model=model,
        route_role=route_role_for_agent(agent_type),
        status="active",
        created_at=now,
        updated_at=now,
        tools=_clean_list(tools or [], max_items=16, max_len=80),
        memory_scope=_memory_scope(memory_scope),
        persona_constraints=_clean_list(persona_constraints or [], max_items=10, max_len=180),
        routing_hints=_clean_list(routing_hints or [], max_items=10, max_len=180),
    )

    path = store_path(cwd)
    existing = [item.to_dict() for item in list_profiles(cwd)]
    existing.insert(0, profile.to_dict())
    _write_store(path, existing)
    return profile


def update_profile(cwd: str | Path, profile_id: str, **values: Any) -> AgentProfile:
    profiles = list_profiles(cwd)
    out: list[dict[str, Any]] = []
    updated: AgentProfile | None = None
    now = _now()
    for profile in profiles:
        data = profile.to_dict()
        if profile.id != profile_id:
            out.append(data)
            continue
        if "name" in values and values["name"] is not None:
            data["name"] = _clean_text(str(values["name"]), fallback=profile.name, max_len=80)
        if "purpose" in values and values["purpose"] is not None:
            data["purpose"] = _clean_text(str(values["purpose"]), fallback=profile.purpose, max_len=600)
        if "agent_type" in values and values["agent_type"] is not None:
            data["agent_type"] = _clean_agent_type(str(values["agent_type"]))
            data["route_role"] = route_role_for_agent(data["agent_type"])
        if "provider" in values and values["provider"] is not None:
            provider = str(values["provider"])
            data["provider"] = provider if provider in settings.PROVIDERS else profile.provider
        if "model" in values and values["model"] is not None:
            data["model"] = str(values["model"]).strip() or profile.model
        if "status" in values and values["status"] is not None:
            data["status"] = _status(str(values["status"]))
        if "tools" in values and values["tools"] is not None:
            data["tools"] = _clean_list(values["tools"], max_items=16, max_len=80)
        if "memory_scope" in values and values["memory_scope"] is not None:
            data["memory_scope"] = _memory_scope(str(values["memory_scope"]))
        if "persona_constraints" in values and values["persona_constraints"] is not None:
            data["persona_constraints"] = _clean_list(values["persona_constraints"], max_items=10, max_len=180)
        if "routing_hints" in values and values["routing_hints"] is not None:
            data["routing_hints"] = _clean_list(values["routing_hints"], max_items=10, max_len=180)
        data["updated_at"] = now
        data["schema_version"] = 2
        updated = _profile_from_raw(data)
        out.append(updated.to_dict())
    if updated is None:
        raise KeyError(f"agent profile not found: {profile_id}")
    _write_store(store_path(cwd), out)
    return updated


def profile_prompt(profile: AgentProfile) -> str:
    lines = [
        f"# Agent Profile: {profile.name}",
        f"- Type: {profile.agent_type}; route: {profile.route_role}; model: {profile.provider}/{profile.model}.",
        f"- Purpose: {profile.purpose}",
        f"- Memory scope: {profile.memory_scope}",
    ]
    if profile.tools:
        lines.append(f"- Tool scope: {', '.join(profile.tools[:8])}")
    if profile.persona_constraints:
        lines.append("- Persona constraints: " + "; ".join(profile.persona_constraints[:5]))
    if profile.routing_hints:
        lines.append("- Routing hints: " + "; ".join(profile.routing_hints[:5]))
    return "\n".join(lines)


def prompt_section(cwd: str | Path, *, limit: int = 6) -> str:
    profiles = [profile for profile in list_profiles(cwd) if profile.status == "active"][: max(1, limit)]
    if not profiles:
        return ""
    lines = ["# Saved Agent Profiles"]
    for profile in profiles:
        tools = f" tools={', '.join(profile.tools[:4])}" if profile.tools else ""
        lines.append(f"- {profile.name}: {profile.agent_type}/{profile.route_role}; memory={profile.memory_scope};{tools} purpose={profile.purpose}")
    return "\n".join(lines)


def _profile_from_raw(raw: dict[str, Any]) -> AgentProfile:
    agent_type = _clean_agent_type(str(raw.get("agent_type", "")))
    default_provider = settings.provider_default({})
    provider = str(raw.get("provider", default_provider))
    provider = provider if provider in settings.PROVIDERS else default_provider
    model = str(raw.get("model") or settings.model_default(provider, {}))
    created_at = str(raw.get("created_at") or _now())
    updated_at = str(raw.get("updated_at") or created_at)
    return AgentProfile(
        id=str(raw["id"]),
        name=_clean_text(str(raw.get("name", "")), fallback="Crypt Agent", max_len=80),
        purpose=_clean_text(str(raw.get("purpose", "")), fallback="Handle delegated work for Crypt.", max_len=600),
        agent_type=agent_type,
        provider=provider,
        model=model,
        route_role=str(raw.get("route_role") or route_role_for_agent(agent_type)),
        status=str(raw.get("status") or "active"),
        created_at=created_at,
        updated_at=updated_at,
        schema_version=int(raw.get("schema_version") or 1),
        tools=_clean_list(raw.get("tools", []), max_items=16, max_len=80),
        memory_scope=_memory_scope(str(raw.get("memory_scope") or "workspace")),
        persona_constraints=_clean_list(raw.get("persona_constraints", []), max_items=10, max_len=180),
        routing_hints=_clean_list(raw.get("routing_hints", []), max_items=10, max_len=180),
    )


def _clean_agent_type(agent_type: str) -> str:
    names = {agent.name for agent in registry.list_agents()}
    return agent_type if agent_type in names else "worker"


def _clean_text(value: str, *, fallback: str, max_len: int) -> str:
    value = " ".join((value or "").strip().split())
    if not value:
        return fallback
    return value[:max_len]


def _clean_list(values: object, *, max_items: int, max_len: int) -> list[str]:
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = _clean_text(str(value), fallback="", max_len=max_len)
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
        if len(out) >= max_items:
            break
    return out


def _memory_scope(value: str) -> str:
    clean = str(value or "").strip().lower()
    return clean if clean in {"workspace", "project", "session", "global"} else "workspace"


def _status(value: str) -> str:
    clean = str(value or "").strip().lower()
    return clean if clean in {"active", "paused", "archived"} else "active"


def _profile_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:36]
    return f"{slug or 'agent'}-{uuid.uuid4().hex[:8]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_store(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _write_store(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(path)
    settings.restrict_file_permissions(path)
