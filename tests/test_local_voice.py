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


def test_local_voice_exposes_distinct_voice_choices():
    voice_ids = {voice["id"] for voice in local_voice.VOICE_CHOICES}

    assert {
        "af_heart",
        "af_bella",
        "af_nicole",
        "af_jessica",
        "am_puck",
        "am_fenrir",
        "am_adam",
        "bf_isabella",
        "bm_george",
    } <= voice_ids
    assert all(voice.get("style") for voice in local_voice.VOICE_CHOICES)


def test_local_voice_removes_emoji_before_synthesis():
    clean = local_voice._clean_text("Got it \U0001f604\U0001f525. Shipped \u2705")

    assert clean == "Got it. Shipped"
    assert "\U0001f604" not in clean
    assert "\u2705" not in clean


def test_local_voice_cleans_markdown_and_links_for_speech():
    clean = local_voice._clean_text("**Done** - see `index.html` and [tracker](https://example.test/a). ```print('skip')```")

    assert clean == "Done - see index.html and tracker. code omitted"


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

    result = local_voice.speak("hello from crypt \U0001f604\U0001f525", voice="af_heart", speed=0.94)

    assert result.voice == "af_heart"
    assert result.audio_url.startswith("/api/voice/audio/kokoro-")
    assert Path(result.path).exists()
    assert calls
    assert "--voice" in calls[0]
    assert "af_heart" in calls[0]
    spoken_text = calls[0][calls[0].index("--text") + 1]
    assert spoken_text == "hello from crypt"
