from __future__ import annotations

from pathlib import Path

from core import onboarding, settings


def _ready_runtime() -> dict:
    return {
        "providerHealth": {"cards": [{"provider": settings.PROVIDER_CRYPT, "label": "Crypt", "status": "ready", "authState": "ready"}]},
        "voice": {"ready": True},
        "memoryJournal": {"longTermCount": 1, "workingCount": 1},
        "approvalPolicy": {"enabled": 5},
        "safetyIncidents": {"critical": 0},
        "repairDoctor": {"critical": 0, "failing": 0, "repairCommands": []},
        "connectorReadiness": {"ready": 1, "total": 10, "needsAuth": 9},
        "trustCalibration": {"averageInitiative": 3.5},
        "remoteAccess": {"enabled": False, "remote": False},
    }


def test_onboarding_ready_when_required_setup_is_complete(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    monkeypatch.setattr(settings, "load_config", lambda: {"provider": settings.PROVIDER_CRYPT, "crypt_model": "crypt-max"})
    workspace = tmp_path / "repo"
    workspace.mkdir()

    snap = onboarding.snapshot(workspace, _ready_runtime())

    assert snap["status"] == "ready"
    assert snap["complete"] == snap["required"]
    assert snap["percent"] == 100


def test_onboarding_surfaces_next_required_setup(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    monkeypatch.setattr(settings, "load_config", lambda: {"provider": settings.PROVIDER_CRYPT, "crypt_model": "crypt-max"})
    workspace = tmp_path / "repo"
    workspace.mkdir()
    runtime = _ready_runtime()
    runtime["providerHealth"] = {"cards": [{"provider": settings.PROVIDER_CRYPT, "label": "Crypt", "status": "missing", "authState": "missing"}]}

    snap = onboarding.snapshot(workspace, runtime)
    prompt = onboarding.prompt_section(workspace, runtime)

    assert snap["status"] == "needs-setup"
    assert snap["nextStep"]["step_id"] == "provider"
    assert "python main.py login --provider crypt" in snap["setupActions"]
    assert "Productized Onboarding" in prompt
