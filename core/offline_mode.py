"""Offline/local-first routing guidance for private or degraded operation."""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

from . import provider_health, settings


PRIVATE_RE = re.compile(r"\b(offline|local only|local-only|private mode|privacy mode|no cloud|air.?gap|on device|on-device)\b", re.I)


@dataclass(frozen=True)
class OfflineDecision:
    enabled: bool
    prefer_local: bool
    reason: str
    provider: str
    model: str
    host: str
    active_provider: str
    active_status: str = ""
    local_ready: bool = False
    constraints: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["constraints"] = list(self.constraints)
        return data


def decide(
    text: str = "",
    *,
    saved: dict | None = None,
    health: dict[str, Any] | None = None,
) -> OfflineDecision:
    saved = settings.load_config() if saved is None else saved
    health = provider_health.snapshot(saved) if health is None else health
    active_provider = settings.provider_default(saved)
    local_provider = settings.PROVIDER_OLLAMA
    local_model = settings.model_default(local_provider, saved)
    local_host = settings.ollama_host(saved=saved)
    active_card = _card(health, active_provider)
    local_card = _card(health, local_provider)
    explicit = _explicit_enabled(saved) or bool(PRIVATE_RE.search(text or ""))
    active_bad = active_provider != local_provider and active_card.get("status") in {"warning", "missing"}
    local_ready = local_card.get("status") in {"ready", "warning"} or local_card.get("authState") == "local"
    prefer_local = explicit or (active_bad and local_ready)
    reason = "private/offline request" if explicit else ("cloud provider degraded" if active_bad else "cloud routing allowed")
    enabled = prefer_local or _explicit_enabled(saved)
    return OfflineDecision(
        enabled=enabled,
        prefer_local=prefer_local,
        reason=reason,
        provider=local_provider,
        model=local_model,
        host=local_host,
        active_provider=active_provider,
        active_status=str(active_card.get("status") or ""),
        local_ready=bool(local_ready),
        constraints=(
            "Prefer local Ollama model and local files/tools.",
            "Avoid cloud web/model calls unless the user explicitly allows them.",
            "External sends, purchases, public posts, and credential use still require approval.",
        ),
    )


def snapshot(saved: dict | None = None, health: dict[str, Any] | None = None) -> dict[str, Any]:
    decision = decide(saved=saved, health=health)
    return {
        **decision.to_dict(),
        "triggerTerms": ["offline", "private mode", "local only", "no cloud"],
        "localTools": ["filesystem", "memory", "artifacts", "office", "local search", "kokoro voice", "ollama"],
    }


def prompt_section(text: str = "", *, saved: dict | None = None, health: dict[str, Any] | None = None) -> str:
    decision = decide(text, saved=saved, health=health)
    if not decision.enabled and not decision.prefer_local:
        return ""
    lines = [
        "# Offline Local Mode",
        f"- prefer_local={decision.prefer_local}; reason={decision.reason}; route={decision.provider}/{decision.model}; host={decision.host}",
    ]
    lines.extend(f"- {constraint}" for constraint in decision.constraints)
    return "\n".join(lines)


def _explicit_enabled(saved: dict[str, Any]) -> bool:
    env = os.getenv("CRYPT_OFFLINE_MODE") or os.getenv("CRYPT_PRIVATE_MODE")
    if env is not None:
        return str(env).strip().lower() in {"1", "true", "yes", "on"}
    return bool(saved.get("offline_mode") or saved.get("private_mode"))


def _card(health: dict[str, Any], provider: str) -> dict[str, Any]:
    for card in health.get("cards", []):
        if str(card.get("provider") or "") == provider:
            return dict(card)
    return {}
