from __future__ import annotations

from core import model_registry, settings


def test_model_registry_labels_clean_crypt_models():
    assert model_registry.label("crypt-max") == "ChatGPT 5.5"
    assert model_registry.label("crypt-spark") == "ChatGPT 5.3 Spark"


def test_model_registry_describes_capabilities():
    info = model_registry.describe(settings.PROVIDER_CRYPT, "crypt-pro")

    assert info.label == "ChatGPT 5 Codex"
    assert "code" in info.capabilities
    assert info.cloud is True


def test_model_registry_marks_local_ollama_models():
    info = model_registry.describe(settings.PROVIDER_OLLAMA, "qwen2.5-coder:14b")

    assert info.local is True
    assert info.cloud is False
    assert "local" in info.capabilities
    assert "code" in info.capabilities
