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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    )

    path = store_path(cwd)
    existing = [item.to_dict() for item in list_profiles(cwd)]
    existing.insert(0, profile.to_dict())
    _write_store(path, existing)
    return profile


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
    )


def _clean_agent_type(agent_type: str) -> str:
    names = {agent.name for agent in registry.list_agents()}
    return agent_type if agent_type in names else "worker"


def _clean_text(value: str, *, fallback: str, max_len: int) -> str:
    value = " ".join((value or "").strip().split())
    if not value:
        return fallback
    return value[:max_len]


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
