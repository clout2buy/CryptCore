"""Smart model routing by task type, reasoning need, cost, and latency."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from . import intent_router, model_registry, settings


@dataclass(frozen=True)
class ModelRouteDecision:
    provider: str
    model: str
    route_role: str
    task_type: str
    reasoning: str
    latency_bias: str
    cost_bias: str
    context_need: str
    tool_need: str
    confidence: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["modelLabel"] = model_registry.label(self.model)
        data["providerLabel"] = _provider_label(self.provider)
        return data


def decide(
    text: str,
    *,
    saved: dict | None = None,
    forced_role: str | None = None,
) -> ModelRouteDecision:
    saved = saved or {}
    route = intent_router.route(text)
    words = re.findall(r"[A-Za-z0-9']+", str(text or "").lower())
    provider = settings.provider_default(saved)
    task_type = route.intent
    route_role = _route_role(route.route_role, forced_role, task_type)
    reasoning = _reasoning_need(task_type, words)
    latency_bias = _latency_bias(task_type, words)
    cost_bias = _cost_bias(reasoning, latency_bias)
    context_need = _context_need(words)
    tool_need = _tool_need(task_type, words)
    model = _model_for(provider, reasoning, task_type, latency_bias, saved)
    confidence = min(0.97, route.confidence + (0.06 if reasoning in {"high", "max"} else 0.0))
    return ModelRouteDecision(
        provider=provider,
        model=model,
        route_role=route_role,
        task_type=task_type,
        reasoning=reasoning,
        latency_bias=latency_bias,
        cost_bias=cost_bias,
        context_need=context_need,
        tool_need=tool_need,
        confidence=round(confidence, 2),
        rationale=_rationale(task_type, reasoning, latency_bias, context_need, tool_need),
    )


def snapshot(saved: dict | None = None) -> dict[str, Any]:
    saved = saved or settings.load_config()
    examples = [
        decide("hi", saved=saved).to_dict(),
        decide("fix the WebUI bug and run tests", saved=saved).to_dict(),
        decide("review this for security risk", saved=saved).to_dict(),
        decide("research the latest provider docs with sources", saved=saved).to_dict(),
        decide("go all out and build the full business system", saved=saved).to_dict(),
    ]
    return {
        "enabled": True,
        "policy": "configured-provider-first",
        "provider": settings.provider_default(saved),
        "examples": examples,
    }


def prompt_section(saved: dict | None = None) -> str:
    data = snapshot(saved)
    lines = ["# Smart Model Router V2"]
    lines.append(
        "Route tasks by task type, reasoning need, latency, cost, context length, and tool need; "
        "stay on the configured provider unless the user changes providers."
    )
    for item in data["examples"][:4]:
        lines.append(
            f"- {item['task_type']} -> {item['provider']} / {item['model']} "
            f"({item['reasoning']} reasoning, {item['latency_bias']} latency)"
        )
    return "\n".join(lines)


def _route_role(intent_role: str, forced_role: str | None, task_type: str) -> str:
    if forced_role:
        return forced_role
    if task_type == "conversation":
        return "fast"
    return intent_role or "planner"


def _reasoning_need(task_type: str, words: list[str]) -> str:
    text = " ".join(words)
    if any(term in text for term in ("all out", "perfect", "advanced", "autonomous", "security", "architecture")):
        return "max"
    if any(term in text for term in ("phase", "business", "revenue", "review", "audit", "debug", "fix", "implement", "build")):
        return "high"
    if task_type in {"code", "business", "external_action", "review"}:
        return "high"
    if task_type in {"conversation", "empty"} or any(term in words for term in ("quick", "fast", "simple")):
        return "low"
    return "medium"


def _latency_bias(task_type: str, words: list[str]) -> str:
    if task_type == "conversation" or any(term in words for term in ("quick", "fast", "small", "tiny")):
        return "fast"
    if any(term in words for term in ("all", "long", "deep", "perfect", "advanced")):
        return "quality"
    return "balanced"


def _cost_bias(reasoning: str, latency_bias: str) -> str:
    if reasoning in {"max", "high"}:
        return "quality"
    if latency_bias == "fast":
        return "low"
    return "balanced"


def _context_need(words: list[str]) -> str:
    count = len(words)
    if count >= 180 or any(term in words for term in ("repository", "codebase", "everything", "hundred")):
        return "long"
    if count >= 50:
        return "medium"
    return "short"


def _tool_need(task_type: str, words: list[str]) -> str:
    text = " ".join(words)
    if task_type in {"code", "file", "browser", "desktop", "business", "external_action"}:
        return "high"
    if any(term in text for term in ("search", "find online", "website", "file", "folder", "test")):
        return "medium"
    return "low"


def _model_for(provider: str, reasoning: str, task_type: str, latency_bias: str, saved: dict) -> str:
    provider = settings.normalize_provider(provider)
    if provider == settings.PROVIDER_CRYPT:
        if latency_bias == "fast" and reasoning == "low":
            return "crypt-spark"
        if reasoning == "max":
            return "crypt-max"
        if task_type in {"code", "file", "browser", "desktop"}:
            return "crypt-pro"
        if reasoning == "high":
            return "crypt-balanced"
        return "crypt-balanced"
    if provider == settings.PROVIDER_OPENAI:
        if latency_bias == "fast" and reasoning == "low":
            return "gpt-5-mini"
        if reasoning == "max":
            return "o3"
        return "gpt-5"
    if provider == settings.PROVIDER_ANTHROPIC:
        if latency_bias == "fast" and reasoning == "low":
            return "claude-haiku-4-5"
        if reasoning == "max":
            return "claude-opus-4-7"
        return "claude-sonnet-4-6"
    if provider == settings.PROVIDER_GEMINI:
        if reasoning in {"max", "high"}:
            return "gemini-2.5-pro"
        return "gemini-2.5-flash"
    if provider == settings.PROVIDER_OLLAMA:
        if reasoning == "max":
            return "qwen3-coder:480b-cloud"
        if task_type in {"code", "file", "browser", "desktop"}:
            return "qwen2.5-coder:14b"
        if latency_bias == "fast":
            return "gpt-oss:20b"
        return str(saved.get("ollama_model") or settings.OLLAMA_MODEL)
    return settings.model_default(provider, saved)


def _provider_label(provider: str) -> str:
    labels = {
        settings.PROVIDER_CRYPT: "Crypt OAuth",
        settings.PROVIDER_OPENAI: "OpenAI compatible",
        settings.PROVIDER_ANTHROPIC: "Anthropic OAuth",
        settings.PROVIDER_GEMINI: "Gemini",
        settings.PROVIDER_OLLAMA: "Ollama",
    }
    return labels.get(settings.normalize_provider(provider), provider)


def _rationale(task_type: str, reasoning: str, latency_bias: str, context_need: str, tool_need: str) -> str:
    return (
        f"{task_type} task, {reasoning} reasoning, {latency_bias} latency bias, "
        f"{context_need} context, {tool_need} tool need"
    )
