from __future__ import annotations

from core import offline_mode, settings


def _health(active_status: str = "ready", local_status: str = "ready"):
    return {
        "cards": [
            {"provider": settings.PROVIDER_CRYPT, "status": active_status, "authState": "ready"},
            {"provider": settings.PROVIDER_OLLAMA, "status": local_status, "authState": "local"},
        ]
    }


def test_offline_mode_prefers_local_for_private_request(monkeypatch):
    monkeypatch.delenv("CRYPT_OFFLINE_MODE", raising=False)
    saved = {"provider": settings.PROVIDER_CRYPT, "ollama_model": "llama3.2"}

    decision = offline_mode.decide("keep this local only, no cloud", saved=saved, health=_health())

    assert decision.prefer_local is True
    assert decision.reason == "private/offline request"
    assert decision.provider == settings.PROVIDER_OLLAMA
    assert decision.model == "llama3.2"
    assert "Offline Local Mode" in offline_mode.prompt_section("private mode", saved=saved, health=_health())


def test_offline_mode_recommends_local_when_cloud_degraded(monkeypatch):
    monkeypatch.delenv("CRYPT_OFFLINE_MODE", raising=False)
    saved = {"provider": settings.PROVIDER_CRYPT}

    decision = offline_mode.decide("normal task", saved=saved, health=_health(active_status="warning"))

    assert decision.prefer_local is True
    assert decision.reason == "cloud provider degraded"
    assert decision.local_ready is True


def test_offline_mode_standby_when_cloud_ready(monkeypatch):
    monkeypatch.delenv("CRYPT_OFFLINE_MODE", raising=False)
    saved = {"provider": settings.PROVIDER_CRYPT}
    snap = offline_mode.snapshot(saved, _health())

    assert snap["enabled"] is False
    assert snap["prefer_local"] is False
    assert snap["triggerTerms"]
