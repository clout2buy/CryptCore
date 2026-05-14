from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core import local_voice, settings


def test_local_voice_status_reports_missing_setup(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")

    status = local_voice.status()

    assert not status.ready
    assert "python environment" in status.missing
    assert status.default_voice == "af_heart"


def test_local_voice_speak_uses_kokoro_runner(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    local_voice.root().mkdir(parents=True)
    local_voice.cache_dir().mkdir(parents=True)
    local_voice.venv_python().parent.mkdir(parents=True)
    local_voice.venv_python().write_text("fake python", encoding="utf-8")
    local_voice.model_path().write_text("fake model", encoding="utf-8")
    local_voice.voices_path().write_text("fake voices", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        out = Path(command[command.index("--out") + 1])
        out.write_bytes(b"RIFF" + b"\0" * 256)
        return SimpleNamespace(returncode=0, stdout=str(out), stderr="")

    monkeypatch.setattr(local_voice.subprocess, "run", fake_run)

    result = local_voice.speak("hello from crypt", voice="af_heart", speed=0.94)

    assert result.voice == "af_heart"
    assert result.audio_url.startswith("/api/voice/audio/kokoro-")
    assert Path(result.path).exists()
    assert calls
    assert "--voice" in calls[0]
    assert "af_heart" in calls[0]
