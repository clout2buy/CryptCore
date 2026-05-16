"""Simulated full-system failure checks for recovery behavior."""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from . import (
    connector_readiness,
    local_voice,
    memory_journal,
    mission_workers,
    onboarding,
    repair_doctor,
    session,
    settings,
)


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ChaosScenario:
    scenario_id: str
    title: str
    category: str
    passed: bool
    observed: str
    expected: str
    repair_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def snapshot(cwd: str | Path) -> dict[str, Any]:
    root = Path(cwd).expanduser().resolve()
    scenarios = run(root)
    passed = [item for item in scenarios if item.passed]
    return {
        "schema": SCHEMA_VERSION,
        "generatedAt": int(time.time()),
        "total": len(scenarios),
        "passed": len(passed),
        "failed": len(scenarios) - len(passed),
        "status": "pass" if len(passed) == len(scenarios) else "fail",
        "scenarios": [item.to_dict() for item in scenarios],
    }


def latest_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "chaos" / "latest.json"


def cached_snapshot(cwd: str | Path, *, max_age_seconds: int = 300) -> dict[str, Any]:
    path = latest_path(cwd)
    now = int(time.time())
    stale: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict) and int(data.get("schema") or 0) == SCHEMA_VERSION:
            stale = data
            if now - int(data.get("generatedAt") or 0) <= max_age_seconds:
                return data
    try:
        data = snapshot(cwd)
    except Exception as exc:
        if stale:
            return {**stale, "stale": True, "cacheError": f"{type(exc).__name__}: {exc}"}
        return {
            "schema": SCHEMA_VERSION,
            "generatedAt": now,
            "total": 1,
            "passed": 0,
            "failed": 1,
            "status": "fail",
            "cacheError": f"{type(exc).__name__}: {exc}",
            "scenarios": [
                ChaosScenario(
                    "chaos-cache-error",
                    "Chaos checks could not refresh",
                    "chaos",
                    False,
                    f"{type(exc).__name__}: {exc}",
                    "cached chaos checks should not crash chat prompt handling",
                    "retry chaos checks outside the prompt request",
                ).to_dict()
            ],
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    settings.restrict_file_permissions(path)
    return data


def run(cwd: str | Path) -> list[ChaosScenario]:
    root = Path(cwd).expanduser().resolve()
    checks: list[Callable[[Path], ChaosScenario]] = [
        _provider_outage,
        _missing_voice_assets,
        _bad_config,
        _stale_webui_state,
        _external_action_gate,
        _corrupt_memory_store,
    ]
    return [_isolated(root, check) for check in checks]


def write_report(cwd: str | Path) -> dict[str, Any]:
    data = snapshot(cwd)
    path = session.project_dir(cwd) / "chaos" / f"chaos-{int(time.time())}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    latest_path(cwd).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    settings.restrict_file_permissions(path)
    settings.restrict_file_permissions(latest_path(cwd))
    return {**data, "path": str(path)}


def prompt_section(cwd: str | Path) -> str:
    data = cached_snapshot(cwd)
    if data["status"] == "pass":
        return ""
    lines = ["# Full-System Chaos Checks"]
    lines.append(f"- status={data['status']} passed={data['passed']}/{data['total']}")
    for scenario in data["scenarios"]:
        if not scenario["passed"]:
            lines.append(f"- {scenario['category']} {scenario['title']}: {scenario['observed']}; repair={scenario['repair_hint']}")
    return "\n".join(lines)


def _provider_outage(root: Path) -> ChaosScenario:
    saved = {"provider": settings.PROVIDER_CRYPT, "crypt_model": "crypt-max"}
    health = {"cards": [{"provider": settings.PROVIDER_CRYPT, "label": "Crypt", "status": "missing", "authState": "missing"}]}
    repair = repair_doctor.snapshot(root, {"providerHealth": health, "voice": {"ready": True}, "jobQueue": {}, "liveReplay": {"total": 1}}, saved=saved, health=health, voice_state={"ready": True})
    ok = repair["critical"] >= 1 and any("login --provider crypt" in command for command in repair["repairCommands"])
    return ChaosScenario(
        "provider-outage",
        "Provider outage is recoverable",
        "provider",
        ok,
        f"critical={repair['critical']} commands={len(repair['repairCommands'])}",
        "repair doctor should require provider login/fallback",
        "python main.py login --provider crypt",
    )


def _missing_voice_assets(root: Path) -> ChaosScenario:
    voice = {"ready": False, "missing": ["kokoro-v1.0.onnx"], "setup_script": str(local_voice.setup_script())}
    repair = repair_doctor.snapshot(root, {"voice": voice, "jobQueue": {}, "liveReplay": {"total": 1}}, saved={"provider": settings.PROVIDER_OLLAMA}, voice_state=voice)
    ok = any("setup_kokoro_voice.ps1" in command for command in repair["repairCommands"])
    return ChaosScenario(
        "missing-voice-assets",
        "Missing voice assets produce setup command",
        "voice",
        ok,
        ", ".join(repair["repairCommands"]),
        "Kokoro setup command should be surfaced",
        str(local_voice.setup_script()),
    )


def _bad_config(root: Path) -> ChaosScenario:
    repair = repair_doctor.snapshot(root, {"voice": {"ready": True}, "jobQueue": {}, "liveReplay": {"total": 1}}, saved={"provider": "mystery-ai"})
    bad = next((item for item in repair["checks"] if item["name"] == "Provider config is valid"), {})
    ok = bool(bad and not bad.get("ok") and bad.get("repair_command"))
    return ChaosScenario(
        "bad-config",
        "Bad provider config is detected",
        "config",
        ok,
        str(bad.get("detail") or ""),
        "unknown provider should fail with config repair command",
        str(bad.get("repair_command") or "python main.py setup"),
    )


def _stale_webui_state(root: Path) -> ChaosScenario:
    runtime = {
        "activeTask": {"task_id": "task_stale"},
        "liveReplay": {"total": 0},
        "jobQueue": {
            "interrupted": 1,
            "failed": 0,
            "jobs": [{"job_id": "job_stale", "title": "stale", "status": "running", "updated_at": int(time.time()) - 9999}],
        },
        "voice": {"ready": True},
    }
    repair = repair_doctor.snapshot(root, runtime, saved={"provider": settings.PROVIDER_OLLAMA}, voice_state={"ready": True})
    ok = any(item["category"] == "webui" and not item["ok"] for item in repair["checks"])
    return ChaosScenario(
        "stale-webui-state",
        "Stale WebUI state is visible",
        "webui",
        ok,
        repair["summary"],
        "repair doctor should flag stale live replay or job queue",
        "restart WebUI or recover job queue",
    )


def _external_action_gate(root: Path) -> ChaosScenario:
    worker = mission_workers.create_worker(root, "Post update to Reddit", prompt="Submit a public Reddit post.")
    cycled = mission_workers.run_cycle(root, worker.worker_id)
    ok = cycled.status == "blocked" and cycled.external_gate_required and not cycled.external_approved
    return ChaosScenario(
        "external-action-gate",
        "External actions stop at approval gate",
        "safety",
        ok,
        f"status={cycled.status} gate={cycled.external_gate_required}",
        "worker should block before external post/send/payment",
        cycled.gate_reason,
    )


def _corrupt_memory_store(root: Path) -> ChaosScenario:
    path = memory_journal.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    snap = memory_journal.snapshot(root)
    onboard = onboarding.snapshot(
        root,
        {
            "providerHealth": {"cards": [{"provider": settings.PROVIDER_OLLAMA, "label": "Ollama", "status": "ready", "authState": "local"}]},
            "voice": {"ready": True},
            "memoryJournal": snap,
            "approvalPolicy": {"enabled": 5},
            "safetyIncidents": {"critical": 0},
            "repairDoctor": {"critical": 0, "failing": 0, "repairCommands": []},
            "connectorReadiness": connector_readiness.snapshot(root),
            "trustCalibration": {"averageInitiative": 3},
            "remoteAccess": {"enabled": False},
        },
    )
    ok = isinstance(snap, dict) and onboard["complete"] >= 1
    return ChaosScenario(
        "corrupt-memory-store",
        "Corrupt memory store degrades safely",
        "memory",
        ok,
        f"memory keys={len(snap)} onboarding={onboard['status']}",
        "memory snapshot should not crash setup",
        "let passive memory recreate the journal on next write",
    )


def _isolated(root: Path, check: Callable[[Path], ChaosScenario]) -> ChaosScenario:
    old_app_dir = settings.APP_DIR
    with tempfile.TemporaryDirectory(prefix="crypt-chaos-", ignore_cleanup_errors=True) as td:
        settings.APP_DIR = Path(td) / "home"
        scenario_root = Path(td) / "repo"
        scenario_root.mkdir(parents=True, exist_ok=True)
        try:
            return check(scenario_root)
        except Exception as exc:
            return ChaosScenario(
                check.__name__.strip("_"),
                check.__name__.replace("_", " "),
                "chaos",
                False,
                f"{type(exc).__name__}: {exc}",
                "scenario should complete without uncaught exceptions",
                "inspect chaos check implementation",
            )
        finally:
            settings.APP_DIR = old_app_dir
