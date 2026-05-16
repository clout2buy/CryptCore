"""One-screen setup readiness for Crypt."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import (
    approval_policy,
    connector_readiness,
    local_voice,
    memory_journal,
    provider_health,
    repair_doctor,
    safety_incidents,
    settings,
    trust_calibration,
    webui_access,
)


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class OnboardingStep:
    step_id: str
    label: str
    category: str
    status: str
    required: bool
    detail: str
    action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def snapshot(cwd: str | Path, runtime_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(cwd).expanduser().resolve()
    runtime = runtime_snapshot if isinstance(runtime_snapshot, dict) else {}
    saved = settings.load_config()
    provider = settings.provider_default(saved)
    health = _dict(runtime.get("providerHealth")) or provider_health.snapshot(saved)
    voice = _dict(runtime.get("voice")) or local_voice.status().to_dict()
    memory = _dict(runtime.get("memoryJournal")) or memory_journal.snapshot(root)
    policy = _dict(runtime.get("approvalPolicy")) or approval_policy.snapshot(root)
    safety = _dict(runtime.get("safetyIncidents")) or safety_incidents.snapshot(root)
    repair = _dict(runtime.get("repairDoctor")) or repair_doctor.snapshot(root, runtime)
    connectors = _dict(runtime.get("connectorReadiness")) or connector_readiness.snapshot(root, runtime)
    trust = _dict(runtime.get("trustCalibration")) or trust_calibration.snapshot(root)
    remote = _dict(runtime.get("remoteAccess")) or webui_access.build("127.0.0.1").to_dict()

    steps = [
        _provider_step(provider, health),
        _voice_step(voice),
        _memory_step(memory),
        _autonomy_step(policy, trust),
        _safety_step(safety, repair),
        _connectors_step(connectors),
        _remote_step(remote),
    ]
    required = [step for step in steps if step.required]
    ready_required = [step for step in required if step.status in {"ready", "optional"}]
    setup_actions = [step.action for step in steps if step.status in {"needs-setup", "warning"} and step.action]
    next_step = next((step for step in steps if step.required and step.status not in {"ready", "optional"}), None)
    return {
        "schema": SCHEMA_VERSION,
        "status": "ready" if len(ready_required) == len(required) else "needs-setup",
        "complete": len(ready_required),
        "required": len(required),
        "total": len(steps),
        "percent": round((len(ready_required) / max(1, len(required))) * 100),
        "steps": [step.to_dict() for step in steps],
        "setupActions": setup_actions,
        "nextStep": next_step.to_dict() if next_step else {},
        "summary": "Crypt is ready for autonomous local work." if not next_step else f"Next setup: {next_step.label}",
    }


def prompt_section(cwd: str | Path, runtime_snapshot: dict[str, Any] | None = None) -> str:
    data = snapshot(cwd, runtime_snapshot)
    if data["status"] == "ready":
        return ""
    lines = ["# Productized Onboarding"]
    lines.append(f"- status={data['status']} complete={data['complete']}/{data['required']} next={data['summary']}")
    for step in data["steps"]:
        if step["required"] and step["status"] != "ready":
            lines.append(f"- {step['status']} {step['label']}: {step['detail']}; action={step['action']}")
    return "\n".join(lines)


def _provider_step(provider: str, health: dict[str, Any]) -> OnboardingStep:
    card = next((item for item in health.get("cards") or [] if item.get("provider") == provider), {})
    ready = card.get("status") == "ready"
    return OnboardingStep(
        "provider",
        "Provider",
        "engine",
        "ready" if ready else "needs-setup",
        True,
        f"{card.get('label') or provider}: {card.get('authState') or 'unknown'}",
        _provider_action(provider) if not ready else "",
    )


def _voice_step(voice: dict[str, Any]) -> OnboardingStep:
    ready = bool(voice.get("ready"))
    missing = ", ".join(str(item) for item in voice.get("missing") or [])
    return OnboardingStep(
        "voice",
        "Local Voice",
        "voice",
        "ready" if ready else "needs-setup",
        False,
        "Kokoro voice is ready." if ready else f"Missing {missing or 'voice assets'}.",
        f'powershell -ExecutionPolicy Bypass -File "{voice.get("setup_script") or local_voice.setup_script()}"' if not ready else "",
    )


def _memory_step(memory: dict[str, Any]) -> OnboardingStep:
    count = int(memory.get("longTermCount") or 0) + int(memory.get("workingCount") or 0)
    return OnboardingStep(
        "memory",
        "Memory",
        "knowledge",
        "ready",
        True,
        f"{count} memory signal(s) available; passive learning is enabled.",
    )


def _autonomy_step(policy: dict[str, Any], trust: dict[str, Any]) -> OnboardingStep:
    enabled = int(policy.get("enabled") or 0)
    average = trust.get("averageInitiative", 0)
    ready = enabled > 0 and float(average or 0) >= 2
    return OnboardingStep(
        "autonomy",
        "Autonomy Rules",
        "autonomy",
        "ready" if ready else "needs-setup",
        True,
        f"{enabled} approval rule(s), trust average {average}/5.",
        "open Settings > Approval Policy and Trust Calibration" if not ready else "",
    )


def _safety_step(safety: dict[str, Any], repair: dict[str, Any]) -> OnboardingStep:
    critical = int(safety.get("critical") or 0) + int(repair.get("critical") or 0)
    failing = int(repair.get("failing") or 0)
    if critical:
        status = "needs-setup"
    elif failing:
        status = "warning"
    else:
        status = "ready"
    action = (repair.get("repairCommands") or ["open Settings > Repair Doctor"])[0] if status != "ready" else ""
    return OnboardingStep(
        "safety",
        "Safety And Repair",
        "safety",
        status,
        True,
        f"{critical} critical issue(s), {failing} repair item(s).",
        action,
    )


def _connectors_step(connectors: dict[str, Any]) -> OnboardingStep:
    ready = int(connectors.get("ready") or 0)
    total = int(connectors.get("total") or 0)
    needs_auth = int(connectors.get("needsAuth") or 0)
    return OnboardingStep(
        "connectors",
        "Connectors",
        "external",
        "ready" if ready else "optional",
        False,
        f"{ready}/{total} connector(s) ready; {needs_auth} need auth.",
        "connect external accounts when a mission needs them" if needs_auth else "",
    )


def _remote_step(remote: dict[str, Any]) -> OnboardingStep:
    enabled = bool(remote.get("enabled") or remote.get("remote"))
    return OnboardingStep(
        "remote",
        "Mobile / Remote Access",
        "access",
        "ready" if enabled else "optional",
        False,
        "Remote access is token protected." if enabled else "Local browser access is active; remote is optional.",
        "python main.py webui --remote --access-token <token>" if not enabled else "",
    )


def _provider_action(provider: str) -> str:
    if provider == settings.PROVIDER_CRYPT:
        return "python main.py login --provider crypt"
    if provider == settings.PROVIDER_ANTHROPIC:
        return "python main.py login --provider anthropic"
    if provider == settings.PROVIDER_GEMINI:
        return "python main.py login --provider gemini"
    if provider == settings.PROVIDER_OPENAI:
        return 'setx OPENAI_API_KEY "<your OpenAI API key>"'
    return "ollama serve"


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
