from __future__ import annotations

import time
from pathlib import Path

from core import auth, provider_health, settings


def test_provider_health_reports_auth_latency_and_success(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    monkeypatch.setattr(settings, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(auth, "AUTH_PATH", tmp_path / "auth.json")
    auth.save_provider(
        settings.PROVIDER_CRYPT,
        {
            "type": settings.PROVIDER_CRYPT,
            "access": "crypt-token",
            "expires": int(time.time() * 1000) + 3_600_000,
        },
    )

    provider_health.record_result(settings.PROVIDER_CRYPT, ok=True, latency_ms=321)
    data = provider_health.snapshot({"provider": settings.PROVIDER_CRYPT})
    cards = {card["provider"]: card for card in data["cards"]}

    assert cards[settings.PROVIDER_CRYPT]["status"] == "ready"
    assert cards[settings.PROVIDER_CRYPT]["authState"] == "ready"
    assert cards[settings.PROVIDER_CRYPT]["successes"] == 1
    assert cards[settings.PROVIDER_CRYPT]["lastLatencyMs"] == 321
    assert data["ready"] >= 1


def test_provider_health_warns_for_expiring_auth(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    monkeypatch.setattr(settings, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(auth, "AUTH_PATH", tmp_path / "auth.json")
    auth.save_provider(
        "anthropic",
        {
            "type": "oauth",
            "access": "anthropic-token",
            "expires": int(time.time() * 1000) + 60_000,
        },
    )

    data = provider_health.snapshot({"provider": settings.PROVIDER_ANTHROPIC})
    anthropic = next(card for card in data["cards"] if card["provider"] == settings.PROVIDER_ANTHROPIC)

    assert anthropic["authState"] == "expiring"
    assert anthropic["status"] == "warning"
    assert anthropic["expiresInSeconds"] > 0


def test_provider_health_records_failures_and_prompt_section(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")

    provider_health.record_result(settings.PROVIDER_OLLAMA, ok=False, latency_ms=50, error="connection refused")
    data = provider_health.snapshot({"provider": settings.PROVIDER_OLLAMA})
    ollama = next(card for card in data["cards"] if card["provider"] == settings.PROVIDER_OLLAMA)
    section = provider_health.prompt_section({"provider": settings.PROVIDER_OLLAMA})

    assert ollama["status"] == "warning"
    assert ollama["failures"] == 1
    assert "connection refused" in ollama["lastError"]
    assert "# Provider Health" in section
