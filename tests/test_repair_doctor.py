from __future__ import annotations

import time
from pathlib import Path

from core import repair_doctor, settings


def _health(status: str = "ready", auth_state: str = "ready") -> dict:
    return {
        "cards": [
            {
                "provider": settings.PROVIDER_CRYPT,
                "label": "Crypt OAuth",
                "status": status,
                "authState": auth_state,
            },
            {
                "provider": settings.PROVIDER_OLLAMA,
                "label": "Ollama",
                "status": "ready",
                "authState": "local",
            },
        ]
    }


def _runtime(health: dict, voice: dict) -> dict:
    return {
        "providerHealth": health,
        "voice": voice,
        "jobQueue": {"failed": 0, "interrupted": 0, "jobs": []},
        "liveReplay": {"total": 1},
    }


def test_repair_doctor_surfaces_missing_voice_setup(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    health = _health()
    voice = {
        "ready": False,
        "root": str(tmp_path / "voice"),
        "missing": ["kokoro-v1.0.onnx", "voices-v1.0.bin"],
        "setup_script": str(Path("scripts") / "setup_kokoro_voice.ps1"),
    }

    snap = repair_doctor.snapshot(
        workspace,
        _runtime(health, voice),
        saved={"provider": settings.PROVIDER_CRYPT, "crypt_model": "crypt-max"},
        health=health,
        voice_state=voice,
    )

    assert snap["failing"] == 1
    assert any("setup_kokoro_voice.ps1" in command for command in snap["repairCommands"])
    assert any(check["category"] == "voice" and not check["ok"] for check in snap["checks"])
    assert "Recovery And Repair Doctor" in repair_doctor.prompt_section(
        workspace,
        _runtime(health, voice),
        saved={"provider": settings.PROVIDER_CRYPT, "crypt_model": "crypt-max"},
        health=health,
    )


def test_repair_doctor_flags_auth_and_stale_jobs(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    health = _health(status="missing", auth_state="missing")
    runtime = _runtime(health, {"ready": True, "root": "voice"})
    runtime["jobQueue"] = {
        "failed": 0,
        "interrupted": 1,
        "jobs": [
            {
                "job_id": "job_old",
                "title": "stale task",
                "status": "running",
                "updated_at": int(time.time()) - repair_doctor.STALE_RUNNING_SECONDS - 5,
            }
        ],
    }

    snap = repair_doctor.snapshot(
        workspace,
        runtime,
        saved={"provider": settings.PROVIDER_CRYPT, "crypt_model": "crypt-max"},
        health=health,
        voice_state={"ready": True, "root": "voice"},
    )

    assert snap["critical"] == 1
    assert snap["warnings"] == 1
    assert "python main.py login --provider crypt" in snap["repairCommands"]
    assert any("job_queue.recover" in command for command in snap["repairCommands"])
