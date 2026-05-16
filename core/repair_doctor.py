"""Structured recovery checks with concrete repair commands."""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import job_queue, live_replay, local_voice, offline_mode, provider_health, session, settings


SCHEMA_VERSION = 1
STALE_RUNNING_SECONDS = 45 * 60


@dataclass(frozen=True)
class RepairCheck:
    name: str
    category: str
    ok: bool
    severity: str = "ok"
    detail: str = ""
    repair_command: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def snapshot(
    cwd: str | Path,
    runtime_snapshot: dict[str, Any] | None = None,
    *,
    saved: dict[str, Any] | None = None,
    health: dict[str, Any] | None = None,
    voice_state: local_voice.VoiceStatus | dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(cwd).expanduser().resolve()
    saved_config = settings.load_config() if saved is None else dict(saved)
    runtime = runtime_snapshot if isinstance(runtime_snapshot, dict) else {}
    health_data = health or _dict(runtime.get("providerHealth")) or provider_health.snapshot(saved_config)
    voice_data = _voice_dict(voice_state) if voice_state is not None else _dict(runtime.get("voice"))
    if not voice_data:
        voice_data = local_voice.status().to_dict()

    checks = [
        _check_app_dir_writable(),
        _check_workspace_state(root),
        _check_config_provider(saved_config),
        _check_config_model(saved_config),
        _check_provider_health(saved_config, health_data),
        _check_voice_assets(voice_data),
        _check_offline_route(saved_config, health_data),
        _check_job_state(root, runtime),
        _check_live_replay(root, runtime),
    ]
    failing = [item for item in checks if not item.ok]
    warnings = [item for item in failing if item.severity == "warning"]
    critical = [item for item in failing if item.severity == "critical"]
    repair_commands = _unique(item.repair_command for item in failing if item.repair_command)
    status = "critical" if critical else "repair" if failing else "ready"
    return {
        "schema": SCHEMA_VERSION,
        "status": status,
        "total": len(checks),
        "passing": len(checks) - len(failing),
        "failing": len(failing),
        "warnings": len(warnings),
        "critical": len(critical),
        "checks": [item.to_dict() for item in checks],
        "repairCommands": repair_commands[:12],
        "summary": _summary(status, failing),
    }


def prompt_section(
    cwd: str | Path,
    runtime_snapshot: dict[str, Any] | None = None,
    *,
    saved: dict[str, Any] | None = None,
    health: dict[str, Any] | None = None,
) -> str:
    data = snapshot(cwd, runtime_snapshot, saved=saved, health=health)
    if not data["failing"]:
        return ""
    lines = ["# Recovery And Repair Doctor"]
    lines.append(f"- status={data['status']} failing={data['failing']} critical={data['critical']}")
    for item in data["checks"]:
        if item.get("ok"):
            continue
        command = f"; repair={item['repair_command']}" if item.get("repair_command") else ""
        lines.append(f"- {item['severity']} {item['name']}: {item['detail']}{command}")
    return "\n".join(lines)


def format_report(cwd: str | Path, runtime_snapshot: dict[str, Any] | None = None) -> str:
    data = snapshot(cwd, runtime_snapshot)
    lines = [f"Crypt repair doctor: {data['passing']}/{data['total']} checks passed ({data['status']})"]
    for item in data["checks"]:
        mark = "OK" if item["ok"] else item["severity"].upper()
        detail = f" - {item['detail']}" if item.get("detail") else ""
        lines.append(f"[{mark}] {item['category']}: {item['name']}{detail}")
        if not item["ok"] and item.get("repair_command"):
            lines.append(f"  repair: {item['repair_command']}")
    return "\n".join(lines)


def _check_app_dir_writable() -> RepairCheck:
    try:
        settings.APP_DIR.mkdir(parents=True, exist_ok=True)
        probe = settings.APP_DIR / ".repair-doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return RepairCheck("App data directory is writable", "storage", True, detail=str(settings.APP_DIR))
    except OSError as exc:
        return RepairCheck(
            "App data directory is writable",
            "storage",
            False,
            "critical",
            f"{settings.APP_DIR}: {exc}",
            repair_command=f'New-Item -ItemType Directory -Force -Path "{settings.APP_DIR}"',
            source="settings.APP_DIR",
        )


def _check_workspace_state(root: Path) -> RepairCheck:
    try:
        root.mkdir(parents=True, exist_ok=True)
        project_dir = session.project_dir(root)
        project_dir.mkdir(parents=True, exist_ok=True)
        probe = project_dir / ".repair-doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return RepairCheck("Workspace state is writable", "storage", True, detail=str(project_dir))
    except OSError as exc:
        return RepairCheck(
            "Workspace state is writable",
            "storage",
            False,
            "critical",
            f"{root}: {exc}",
            repair_command=f'New-Item -ItemType Directory -Force -Path "{root}"',
            source="workspace",
        )


def _check_config_provider(saved: dict[str, Any]) -> RepairCheck:
    raw = os.getenv("CRYPT_PROVIDER") or str(saved.get("provider") or "")
    if raw and settings.normalize_provider(raw) not in settings.PROVIDERS:
        return RepairCheck(
            "Provider config is valid",
            "config",
            False,
            "critical",
            f"unknown provider {raw!r}",
            repair_command=_update_config_command(provider=settings.PROVIDER_CRYPT),
            source="settings.config",
        )
    provider = settings.provider_default(saved)
    return RepairCheck("Provider config is valid", "config", True, detail=provider)


def _check_config_model(saved: dict[str, Any]) -> RepairCheck:
    provider = settings.provider_default(saved)
    model = settings.model_default(provider, saved)
    known = _known_models(provider)
    if provider == settings.PROVIDER_OLLAMA:
        if model in known:
            return RepairCheck("Model config is usable", "config", True, detail=f"{provider}/{model}")
        return RepairCheck("Model config is usable", "config", True, detail=f"{provider}/{model} custom local model")
    if model in known:
        return RepairCheck("Model config is usable", "config", True, detail=f"{provider}/{model}")
    return RepairCheck(
        "Model config is usable",
        "config",
        False,
        "warning",
        f"{provider}/{model} is not in the known model list",
        repair_command=_update_config_command(**{_model_key(provider): _default_model(provider)}),
        source="settings.config",
    )


def _check_provider_health(saved: dict[str, Any], health: dict[str, Any]) -> RepairCheck:
    provider = settings.provider_default(saved)
    card = _provider_card(health, provider)
    if not card:
        return RepairCheck(
            "Active provider is reachable",
            "provider",
            False,
            "critical",
            f"no provider health card for {provider}",
            repair_command="python main.py setup",
            source="provider_health",
        )
    status = str(card.get("status") or "")
    auth_state = str(card.get("authState") or "")
    detail = f"{card.get('label') or provider}: status={status} auth={auth_state}"
    if status == "ready":
        return RepairCheck("Active provider is reachable", "provider", True, detail=detail)
    severity = "critical" if auth_state in {"missing", "expired"} else "warning"
    return RepairCheck(
        "Active provider is reachable",
        "provider",
        False,
        severity,
        detail,
        repair_command=_provider_repair_command(provider, auth_state),
        source="provider_health",
    )


def _check_voice_assets(voice: dict[str, Any]) -> RepairCheck:
    if voice.get("ready"):
        return RepairCheck("Local voice assets are installed", "voice", True, detail=str(voice.get("root") or "kokoro"))
    missing = [str(item) for item in voice.get("missing") or []]
    setup_script = str(voice.get("setup_script") or local_voice.setup_script())
    return RepairCheck(
        "Local voice assets are installed",
        "voice",
        False,
        "warning",
        "missing " + ", ".join(missing or ["voice assets"]),
        repair_command=f'powershell -ExecutionPolicy Bypass -File "{setup_script}"',
        source="local_voice",
    )


def _check_offline_route(saved: dict[str, Any], health: dict[str, Any]) -> RepairCheck:
    offline = offline_mode.snapshot(saved, health)
    if offline.get("prefer_local") and not offline.get("localReady"):
        return RepairCheck(
            "Offline fallback can run",
            "provider",
            False,
            "critical",
            f"local route requested but {offline.get('host') or 'Ollama'} is not ready",
            repair_command="ollama serve",
            source="offline_mode",
        )
    status = "local ready" if offline.get("localReady") else "cloud routing allowed"
    return RepairCheck("Offline fallback can run", "provider", True, detail=status)


def _check_job_state(root: Path, runtime: dict[str, Any]) -> RepairCheck:
    queue = _dict(runtime.get("jobQueue")) or job_queue.snapshot(root)
    jobs = queue.get("jobs") if isinstance(queue.get("jobs"), list) else []
    now = int(time.time())
    stale = [
        str(job.get("title") or job.get("job_id") or "job")
        for job in jobs
        if str(job.get("status") or "") == "running"
        and int(job.get("updated_at") or 0)
        and now - int(job.get("updated_at") or 0) > STALE_RUNNING_SECONDS
    ]
    interrupted = int(queue.get("interrupted") or 0)
    failed = int(queue.get("failed") or 0)
    if stale or interrupted:
        detail = f"stale={len(stale)} interrupted={interrupted} failed={failed}"
        return RepairCheck(
            "Job queue has no stale running work",
            "webui",
            False,
            "warning",
            detail,
            repair_command=f'python -c "from core import job_queue; job_queue.recover({str(root)!r})"',
            source="job_queue",
        )
    return RepairCheck("Job queue has no stale running work", "webui", True, detail=f"failed={failed}")


def _check_live_replay(root: Path, runtime: dict[str, Any]) -> RepairCheck:
    replay = _dict(runtime.get("liveReplay")) or live_replay.snapshot(root)
    active_task = runtime.get("activeTask")
    total = int(replay.get("total") or 0)
    if active_task and total == 0:
        return RepairCheck(
            "Live activity replay is attached",
            "webui",
            False,
            "warning",
            "active task exists but no replay events are available yet",
            repair_command="python main.py webui --open",
            source="live_replay",
        )
    path = live_replay.replay_path(root)
    if path.exists():
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size > 5_000_000:
            return RepairCheck(
                "Live activity replay is attached",
                "webui",
                False,
                "warning",
                f"replay log is large ({size} bytes)",
                repair_command="restart the WebUI after archiving old live replay logs",
                source="live_replay",
            )
    return RepairCheck("Live activity replay is attached", "webui", True, detail=f"{total} replay events")


def _provider_card(health: dict[str, Any], provider: str) -> dict[str, Any] | None:
    for card in health.get("cards") or []:
        if str(card.get("provider") or "") == provider:
            return card
    return None


def _provider_repair_command(provider: str, auth_state: str) -> str:
    if provider == settings.PROVIDER_CRYPT:
        return "python main.py login --provider crypt"
    if provider == settings.PROVIDER_ANTHROPIC:
        return "python main.py login --provider anthropic"
    if provider == settings.PROVIDER_GEMINI:
        return "python main.py login --provider gemini"
    if provider == settings.PROVIDER_OPENAI:
        return 'setx OPENAI_API_KEY "<your OpenAI API key>"'
    if provider == settings.PROVIDER_OLLAMA:
        return "ollama serve"
    if auth_state in {"missing", "expired"}:
        return "python main.py setup"
    return ""


def _known_models(provider: str) -> tuple[str, ...]:
    if provider == settings.PROVIDER_ANTHROPIC:
        return settings.ANTHROPIC_MODELS
    if provider == settings.PROVIDER_OPENAI:
        return settings.OPENAI_MODELS
    if provider == settings.PROVIDER_CRYPT:
        return settings.CRYPT_MODELS
    if provider == settings.PROVIDER_GEMINI:
        return settings.GEMINI_MODELS
    return (*settings.OLLAMA_LOCAL_MODELS, *settings.OLLAMA_CLOUD_MODELS)


def _model_key(provider: str) -> str:
    return {
        settings.PROVIDER_ANTHROPIC: "anthropic_model",
        settings.PROVIDER_OPENAI: "openai_model",
        settings.PROVIDER_CRYPT: "crypt_model",
        settings.PROVIDER_GEMINI: "gemini_model",
        settings.PROVIDER_OLLAMA: "ollama_model",
    }.get(provider, "model")


def _default_model(provider: str) -> str:
    return {
        settings.PROVIDER_ANTHROPIC: settings.ANTHROPIC_MODEL,
        settings.PROVIDER_OPENAI: settings.OPENAI_MODEL,
        settings.PROVIDER_CRYPT: settings.CRYPT_MODEL,
        settings.PROVIDER_GEMINI: settings.GEMINI_MODEL,
        settings.PROVIDER_OLLAMA: settings.OLLAMA_MODEL,
    }.get(provider, settings.CRYPT_MODEL)


def _update_config_command(**values: str) -> str:
    args = ", ".join(f"{key}={value!r}" for key, value in values.items())
    return f'python -c "from core import settings; settings.update_config({args})"'


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _voice_dict(value: local_voice.VoiceStatus | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, local_voice.VoiceStatus):
        return value.to_dict()
    return _dict(value)


def _unique(values) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _summary(status: str, failing: list[RepairCheck]) -> str:
    if not failing:
        return "Runtime setup looks healthy."
    labels = ", ".join(item.name for item in failing[:3])
    if len(failing) > 3:
        labels += f", +{len(failing) - 3} more"
    return f"{status}: {labels}"
