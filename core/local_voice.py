"""Local Kokoro text-to-speech integration for the WebUI."""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from . import redact, settings


MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 0.96
MAX_TEXT_CHARS = 1_400


VOICE_CHOICES = [
    {"id": "af_heart", "label": "Heart", "accent": "US", "grade": "A"},
    {"id": "af_bella", "label": "Bella", "accent": "US", "grade": "A-"},
    {"id": "af_nicole", "label": "Nicole", "accent": "US", "grade": "B-"},
    {"id": "af_sarah", "label": "Sarah", "accent": "US", "grade": "C+"},
    {"id": "am_fenrir", "label": "Fenrir", "accent": "US", "grade": "C+"},
    {"id": "am_michael", "label": "Michael", "accent": "US", "grade": "C+"},
    {"id": "bf_emma", "label": "Emma", "accent": "UK", "grade": "B-"},
    {"id": "bm_fable", "label": "Fable", "accent": "UK", "grade": "C"},
]


@dataclass(frozen=True)
class VoiceStatus:
    ready: bool
    root: str
    python: str
    model: str
    voices_file: str
    setup_script: str
    default_voice: str = DEFAULT_VOICE
    default_speed: float = DEFAULT_SPEED
    voices: list[dict] | None = None
    missing: list[str] | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["voices"] = list(self.voices or VOICE_CHOICES)
        data["missing"] = list(self.missing or [])
        return data


@dataclass(frozen=True)
class SpeechResult:
    audio_id: str
    audio_url: str
    path: str
    voice: str
    speed: float
    chars: int

    def to_dict(self) -> dict:
        return asdict(self)


def root() -> Path:
    return settings.APP_DIR / "voice" / "kokoro"


def cache_dir() -> Path:
    return settings.APP_DIR / "voice" / "cache"


def venv_python() -> Path:
    folder = "Scripts" if os.name == "nt" else "bin"
    exe = "python.exe" if os.name == "nt" else "python"
    return root() / ".venv" / folder / exe


def model_path() -> Path:
    return root() / "kokoro-v1.0.onnx"


def voices_path() -> Path:
    return root() / "voices-v1.0.bin"


def setup_script() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "setup_kokoro_voice.ps1"


def synth_script() -> Path:
    return Path(__file__).resolve().parents[1] / "scripts" / "kokoro_say.py"


def status() -> VoiceStatus:
    missing = []
    if not venv_python().exists():
        missing.append("python environment")
    if not model_path().exists():
        missing.append("kokoro-v1.0.onnx")
    if not voices_path().exists():
        missing.append("voices-v1.0.bin")
    if not synth_script().exists():
        missing.append("kokoro runner")
    return VoiceStatus(
        ready=not missing,
        root=str(root()),
        python=str(venv_python()),
        model=str(model_path()),
        voices_file=str(voices_path()),
        setup_script=str(setup_script()),
        voices=VOICE_CHOICES,
        missing=missing,
    )


def speak(text: str, *, voice: str = DEFAULT_VOICE, speed: float = DEFAULT_SPEED) -> SpeechResult:
    state = status()
    if not state.ready:
        raise RuntimeError(f"Kokoro voice is not ready; run {state.setup_script}")
    clean = _clean_text(text)
    if not clean:
        raise ValueError("voice text is empty")
    voice = _voice_id(voice)
    speed = _speed(speed)
    cache_dir().mkdir(parents=True, exist_ok=True)
    audio_id = f"kokoro-{int(time.time())}-{uuid.uuid4().hex[:8]}.wav"
    out = cache_dir() / audio_id
    command = [
        str(venv_python()),
        str(synth_script()),
        "--model",
        str(model_path()),
        "--voices",
        str(voices_path()),
        "--out",
        str(out),
        "--voice",
        voice,
        "--speed",
        f"{speed:.2f}",
        "--lang",
        _lang_for_voice(voice),
        "--text",
        clean,
    ]
    proc = subprocess.run(
        command,
        cwd=str(root()),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown Kokoro error").strip()
        raise RuntimeError(f"Kokoro voice failed: {detail[:800]}")
    if not out.exists() or out.stat().st_size <= 128:
        raise RuntimeError("Kokoro voice did not produce audio")
    settings.restrict_file_permissions(out)
    return SpeechResult(
        audio_id=audio_id,
        audio_url=f"/api/voice/audio/{audio_id}",
        path=str(out),
        voice=voice,
        speed=speed,
        chars=len(clean),
    )


def audio_path(name: str) -> Path:
    safe = Path(str(name or "")).name
    if not safe.endswith(".wav"):
        raise FileNotFoundError("unsupported voice audio")
    path = (cache_dir() / safe).resolve()
    root_path = cache_dir().resolve()
    if root_path not in path.parents and path != root_path:
        raise FileNotFoundError("voice audio outside cache")
    if not path.exists():
        raise FileNotFoundError(safe)
    return path


def _clean_text(text: str) -> str:
    clean = " ".join(redact.text(str(text or "")).split())
    if len(clean) > MAX_TEXT_CHARS:
        clean = clean[:MAX_TEXT_CHARS].rsplit(" ", 1)[0].strip()
    return clean


def _voice_id(value: str) -> str:
    requested = str(value or "").strip()
    allowed = {item["id"] for item in VOICE_CHOICES}
    return requested if requested in allowed else DEFAULT_VOICE


def _speed(value: float) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        speed = DEFAULT_SPEED
    return max(0.75, min(1.25, speed))


def _lang_for_voice(voice: str) -> str:
    return "en-gb" if voice.startswith(("bf_", "bm_")) else "en-us"
