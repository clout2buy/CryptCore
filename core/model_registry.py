"""Display and routing metadata for provider models."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from . import settings


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    tier: str
    capabilities: tuple[str, ...]
    local: bool = False
    cloud: bool = True

    def to_dict(self) -> dict:
        data = asdict(self)
        data["capabilities"] = list(self.capabilities)
        return data


MODEL_LABELS = {
    "crypt-pro": "ChatGPT 5 Codex",
    "crypt-max": "ChatGPT 5.5",
    "crypt-balanced": "ChatGPT 5.4",
    "crypt-fast": "ChatGPT 5.4 Mini",
    "crypt-legacy": "ChatGPT 5.3 Codex",
    "crypt-spark": "ChatGPT 5.3 Spark",
    "crypt-mini": "Codex Mini",
    "gpt-5-codex": "ChatGPT 5 Codex",
    "gpt-5.3-codex": "ChatGPT 5.3 Codex",
    "gpt-5.3-codex-spark": "ChatGPT 5.3 Spark",
    "gpt-5.4-mini": "ChatGPT 5.4 Mini",
    "gpt-5.4": "ChatGPT 5.4",
    "gpt-5.5": "ChatGPT 5.5",
    "gpt-5": "GPT-5",
    "gpt-5-mini": "GPT-5 Mini",
    "gpt-4.1": "GPT-4.1",
    "gpt-4.1-mini": "GPT-4.1 Mini",
    "o3": "OpenAI o3",
    "o3-mini": "OpenAI o3 Mini",
    "claude-opus-4-7": "Claude Opus 4.7",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
    "gemini-3-flash-preview": "Gemini 3 Flash Preview",
}


def describe(provider: str, model: str) -> ModelInfo:
    provider = settings.normalize_provider(provider)
    model = str(model or "").strip()
    return ModelInfo(
        id=model,
        label=label(model),
        tier=_tier(provider, model),
        capabilities=_capabilities(provider, model),
        local=provider == settings.PROVIDER_OLLAMA and not settings.is_ollama_cloud_model(model),
        cloud=not (provider == settings.PROVIDER_OLLAMA and not settings.is_ollama_cloud_model(model)),
    )


def describe_many(provider: str, models: list[str] | tuple[str, ...]) -> list[dict]:
    return [describe(provider, model).to_dict() for model in models]


def label(model: str) -> str:
    raw = str(model or "").strip()
    if raw in MODEL_LABELS:
        return MODEL_LABELS[raw]
    return (
        raw.replace(":cloud", " Cloud")
        .replace("-cloud", " Cloud")
        .replace(":", " ")
        .replace("_", " ")
        .replace("-", " ")
        .title()
        .replace("Gpt", "GPT")
        .replace("Ui", "UI")
        .replace("Api", "API")
    )


def _tier(provider: str, model: str) -> str:
    lowered = model.lower()
    if any(token in lowered for token in ("mini", "lite", "haiku", "flash", "3b", "4b", "7b", "8b")):
        return "fast"
    if any(token in lowered for token in ("5.5", "opus", "pro", "480b", "235b", "120b", "106b")):
        return "max"
    if provider == settings.PROVIDER_OLLAMA and not settings.is_ollama_cloud_model(model):
        return "local"
    return "balanced"


def _capabilities(provider: str, model: str) -> tuple[str, ...]:
    lowered = model.lower()
    display = label(model).lower()
    capabilities = ["chat"]
    if any(token in lowered for token in ("codex", "coder", "devstral")) or "codex" in display:
        capabilities.append("code")
    if any(token in lowered for token in ("opus", "pro", "5.5", "480b", "235b", "120b", "106b")):
        capabilities.append("deep-reasoning")
    if any(token in lowered for token in ("mini", "lite", "haiku", "flash")):
        capabilities.append("low-latency")
    if "vl" in lowered or provider == settings.PROVIDER_GEMINI:
        capabilities.append("vision")
    if provider == settings.PROVIDER_OLLAMA and not settings.is_ollama_cloud_model(model):
        capabilities.append("local")
    return tuple(dict.fromkeys(capabilities))
