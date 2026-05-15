"""Provider health cards for auth, errors, latency, and fallback routing."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import auth, model_registry, settings


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProviderRunState:
    provider: str
    successes: int = 0
    failures: int = 0
    last_ok: bool | None = None
    last_error: str = ""
    last_latency_ms: int = 0
    updated_at: int = 0


def state_path() -> Path:
    return settings.APP_DIR / "provider-health.json"


def record_result(provider: str, *, ok: bool, latency_ms: int = 0, error: str = "") -> ProviderRunState:
    provider = settings.normalize_provider(provider)
    states = {item.provider: item for item in _read_states()}
    existing = states.get(provider) or ProviderRunState(provider=provider)
    state = ProviderRunState(
        provider=provider,
        successes=existing.successes + (1 if ok else 0),
        failures=existing.failures + (0 if ok else 1),
        last_ok=bool(ok),
        last_error="" if ok else _clip(error, 500),
        last_latency_ms=max(0, int(latency_ms or 0)),
        updated_at=int(time.time()),
    )
    states[provider] = state
    _write_states(list(states.values()))
    return state


def snapshot(saved: dict | None = None) -> dict[str, Any]:
    saved = saved or settings.load_config()
    states = {item.provider: item for item in _read_states()}
    cards = [_card(provider, saved, states.get(provider)) for provider in settings.PROVIDERS]
    ready = [item for item in cards if item["status"] == "ready"]
    warnings = [item for item in cards if item["status"] == "warning"]
    missing = [item for item in cards if item["status"] == "missing"]
    return {
        "total": len(cards),
        "ready": len(ready),
        "warnings": len(warnings),
        "missing": len(missing),
        "recommendedFallback": _fallback(cards, settings.provider_default(saved)),
        "cards": cards,
    }


def prompt_section(saved: dict | None = None) -> str:
    data = snapshot(saved)
    lines = ["# Provider Health"]
    lines.append(
        f"- ready={data['ready']} warning={data['warnings']} missing={data['missing']} "
        f"fallback={data['recommendedFallback'] or 'none'}"
    )
    for card in data["cards"][:5]:
        lines.append(
            f"- {card['provider']}: {card['status']}; auth={card['authState']}; "
            f"model={card['modelLabel']}; failures={card['failures']}; latency={card['lastLatencyMs'] or card['estimatedLatencyMs']}ms"
        )
    return "\n".join(lines)


def _card(provider: str, saved: dict, state: ProviderRunState | None) -> dict[str, Any]:
    provider = settings.normalize_provider(provider)
    model = settings.model_default(provider, saved)
    auth_state, auth_detail, expires_at, expires_in = _auth_state(provider)
    last_error = state.last_error if state else ""
    failures = state.failures if state else 0
    status = _status(provider, auth_state, expires_in, failures, state.last_ok if state else None)
    return {
        "provider": provider,
        "label": _label(provider),
        "model": model,
        "modelLabel": model_registry.label(model),
        "status": status,
        "authState": auth_state,
        "authDetail": auth_detail,
        "expiresAt": expires_at,
        "expiresInSeconds": expires_in,
        "successes": state.successes if state else 0,
        "failures": failures,
        "lastOk": state.last_ok if state else None,
        "lastError": last_error,
        "lastLatencyMs": state.last_latency_ms if state else 0,
        "estimatedLatencyMs": _estimated_latency(provider, model),
        "updatedAt": state.updated_at if state else 0,
        "recommendation": _recommendation(provider, status, auth_state, last_error),
    }


def _auth_state(provider: str) -> tuple[str, str, int, int]:
    now_ms = int(time.time() * 1000)
    if provider == settings.PROVIDER_OLLAMA:
        return "local", "local Ollama endpoint", 0, 0
    if provider == settings.PROVIDER_OPENAI:
        return ("ready", "OPENAI_API_KEY", 0, 0) if os.getenv("OPENAI_API_KEY") else ("missing", "missing OPENAI_API_KEY", 0, 0)
    if provider == settings.PROVIDER_ANTHROPIC and os.getenv("ANTHROPIC_API_KEY"):
        return "ready", "ANTHROPIC_API_KEY", 0, 0
    if provider == settings.PROVIDER_GEMINI and os.getenv("GEMINI_API_KEY"):
        return "ready", "GEMINI_API_KEY", 0, 0
    record = auth.load_provider(provider)
    if provider == settings.PROVIDER_CRYPT and not record:
        record = auth.load_provider("chatgpt") or auth.load_provider("openai-codex")
    if not record:
        return "missing", f"missing {_label(provider)} auth", 0, 0
    expires_at = _expires_at(record)
    expires_in = int((expires_at - now_ms) / 1000) if expires_at else 0
    if expires_at and expires_in <= 0:
        return "expired", "stored OAuth expired", expires_at, expires_in
    if expires_at and expires_in <= 15 * 60:
        return "expiring", "stored OAuth expires soon", expires_at, expires_in
    return "ready", str(record.get("type") or "stored auth"), expires_at, expires_in


def _status(provider: str, auth_state: str, expires_in: int, failures: int, last_ok: bool | None) -> str:
    if auth_state in {"missing", "expired"}:
        return "missing"
    if auth_state == "expiring" or failures >= 3 or last_ok is False:
        return "warning"
    return "ready"


def _fallback(cards: list[dict[str, Any]], active_provider: str) -> str:
    for card in cards:
        if card["provider"] != active_provider and card["status"] == "ready":
            return str(card["provider"])
    for card in cards:
        if card["status"] == "ready":
            return str(card["provider"])
    return ""


def _recommendation(provider: str, status: str, auth_state: str, last_error: str) -> str:
    if status == "ready":
        return "usable"
    if auth_state in {"missing", "expired"}:
        return "login or configure credentials before routing work here"
    if last_error:
        return "use fallback provider until this error is cleared"
    return "watch provider before assigning important work"


def _estimated_latency(provider: str, model: str) -> int:
    lowered = model.lower()
    if provider == settings.PROVIDER_OLLAMA and not settings.is_ollama_cloud_model(model):
        return 900
    if any(token in lowered for token in ("mini", "flash", "haiku", "spark", "lite")):
        return 1200
    if any(token in lowered for token in ("opus", "5.5", "o3", "480b", "235b")):
        return 4200
    return 2200


def _expires_at(record: dict[str, Any]) -> int:
    raw = record.get("expires")
    if isinstance(raw, (int, float)):
        return int(raw)
    creds = record.get("credentials") if isinstance(record.get("credentials"), dict) else {}
    raw = creds.get("expiry") or record.get("expiry")
    if isinstance(raw, str):
        try:
            from datetime import datetime

            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return 0
    return 0


def _label(provider: str) -> str:
    return {
        settings.PROVIDER_ANTHROPIC: "Anthropic",
        settings.PROVIDER_OPENAI: "OpenAI",
        settings.PROVIDER_CRYPT: "Crypt OAuth",
        settings.PROVIDER_GEMINI: "Gemini",
        settings.PROVIDER_OLLAMA: "Ollama",
    }.get(provider, provider)


def _read_states() -> list[ProviderRunState]:
    path = state_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[ProviderRunState] = []
    for item in data.get("providers", []):
        if not isinstance(item, dict):
            continue
        try:
            provider = settings.normalize_provider(str(item.get("provider") or ""))
            if provider not in settings.PROVIDERS:
                continue
            out.append(
                ProviderRunState(
                    provider=provider,
                    successes=int(item.get("successes") or 0),
                    failures=int(item.get("failures") or 0),
                    last_ok=item.get("last_ok") if isinstance(item.get("last_ok"), bool) else None,
                    last_error=str(item.get("last_error") or ""),
                    last_latency_ms=int(item.get("last_latency_ms") or 0),
                    updated_at=int(item.get("updated_at") or 0),
                )
            )
        except Exception:
            continue
    return out


def _write_states(states: list[ProviderRunState]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "providers": [asdict(item) for item in states]}, indent=2),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _clip(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
