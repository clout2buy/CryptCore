"""Per-domain initiative calibration from user signals."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import session, settings


SCHEMA_VERSION = 1
DOMAINS = ("code", "ui", "business", "research", "memory", "personal", "external", "finance", "system")
RISKS = {"low", "medium", "high", "critical"}
AUTONOMY_RE = re.compile(r"\b(do it all|go all out|no stopping|autonomous|fully autonomous|you decide|handle it|i trust|keep going|don't ask)\b", re.I)
CAUTION_RE = re.compile(r"\b(ask me|ask first|don't do|do not do|stop|too much|not what i wanted|wrong|trash|skimped|before you)\b", re.I)
EXTERNAL_RE = re.compile(r"\b(email|gmail|reddit|post|publish|send|dm|stripe|payment|purchase|buy|account|login|credential)\b", re.I)
FINANCE_RE = re.compile(r"\b(stripe|payment|purchase|buy|spend|refund|charge|invoice|revenue|income|money)\b", re.I)
UI_RE = re.compile(r"\b(ui|design|frontend|layout|panel|animation|webui|button|input|chat)\b", re.I)
CODE_RE = re.compile(r"\b(code|repo|test|bug|fix|build|implement|commit|push|phase|runtime)\b", re.I)
BUSINESS_RE = re.compile(r"\b(business|startup|lead|customer|sales|product|launch|brand)\b", re.I)
RESEARCH_RE = re.compile(r"\b(search|research|find|look up|source|web|online)\b", re.I)
MEMORY_RE = re.compile(r"\b(remember|memory|learn|lesson|persona|soul)\b", re.I)


@dataclass(frozen=True)
class TrustProfile:
    domain: str
    initiative: int
    ask_threshold: str = "high"
    notes: list[str] = field(default_factory=list)
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrustSignal:
    signal_id: str
    domain: str
    delta: int
    text: str
    source: str = "chat"
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrustDecision:
    domain: str
    action: str
    initiative: int
    risk: str
    reason: str
    approval_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calibration_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "trust" / "calibration.json"


def observe(cwd: str | Path, text: str, *, intent: str = "", source: str = "chat") -> TrustSignal | None:
    clean = _clean(text, 500)
    if not clean:
        return None
    domain = classify_domain(clean, intent=intent)
    delta = _signal_delta(clean, domain)
    if delta == 0:
        return None
    root = Path(cwd).expanduser().resolve()
    data = _read(root)
    profiles = {item.domain: item for item in data["profiles"]}
    profile = profiles.get(domain) or _default_profile(domain)
    updated = replace(
        profile,
        initiative=max(0, min(5, profile.initiative + delta)),
        notes=_dedupe([_signal_note(delta, clean), *profile.notes])[:10],
        updated_at=_now(),
    )
    profiles[domain] = updated
    signal = TrustSignal(
        signal_id="trust_" + str(abs(hash((domain, clean, _now()))))[:12],
        domain=domain,
        delta=delta,
        text=clean,
        source=_clean(source, 40) or "chat",
        created_at=_now(),
    )
    _write(root, list(profiles.values()), [signal, *data["signals"][:99]])
    return signal


def decide(cwd: str | Path, text: str, *, intent: str = "", risk: str = "medium") -> TrustDecision:
    domain = classify_domain(text, intent=intent)
    profile = _profile(cwd, domain)
    clean_risk = _risk(risk)
    external_write = bool(EXTERNAL_RE.search(text or ""))
    finance = domain == "finance" or bool(FINANCE_RE.search(text or ""))
    if clean_risk == "critical" or finance:
        return TrustDecision(domain, "ask", profile.initiative, clean_risk, "money, credentials, or critical risk require explicit approval", True)
    if domain == "external" and external_write:
        return TrustDecision(domain, "draft", profile.initiative, clean_risk, "external actions are draft-first and approval-gated", True)
    if profile.initiative >= 4 and clean_risk in {"low", "medium"}:
        return TrustDecision(domain, "execute", profile.initiative, clean_risk, "user preference favors initiative in this domain")
    if profile.initiative >= 3 and clean_risk != "high":
        return TrustDecision(domain, "draft", profile.initiative, clean_risk, "prepare useful work, then continue when safe")
    return TrustDecision(domain, "ask", profile.initiative, clean_risk, "user preference favors confirmation here", True)


def snapshot(cwd: str | Path) -> dict[str, Any]:
    data = _read(cwd)
    profiles = sorted(data["profiles"], key=lambda item: DOMAINS.index(item.domain) if item.domain in DOMAINS else 99)
    return {
        "schema": SCHEMA_VERSION,
        "averageInitiative": round(sum(item.initiative for item in profiles) / max(1, len(profiles)), 2),
        "domains": [item.to_dict() for item in profiles],
        "signals": [item.to_dict() for item in data["signals"][:20]],
    }


def prompt_section(cwd: str | Path, text: str = "", *, intent: str = "", risk: str = "medium") -> str:
    decision = decide(cwd, text, intent=intent, risk=risk)
    profile = _profile(cwd, decision.domain)
    return (
        "# User Trust Calibration\n"
        f"- domain={decision.domain}; action={decision.action}; initiative={decision.initiative}/5; "
        f"risk={decision.risk}; approval_required={decision.approval_required}; reason={decision.reason}\n"
        f"- notes={'; '.join(profile.notes[:3]) or 'use default initiative profile'}"
    )


def classify_domain(text: str, *, intent: str = "") -> str:
    lowered = f"{intent} {text}".lower()
    if FINANCE_RE.search(lowered):
        return "finance"
    if EXTERNAL_RE.search(lowered):
        return "external"
    if UI_RE.search(lowered):
        return "ui"
    if BUSINESS_RE.search(lowered):
        return "business"
    if RESEARCH_RE.search(lowered):
        return "research"
    if MEMORY_RE.search(lowered):
        return "memory"
    if CODE_RE.search(lowered):
        return "code"
    if any(term in lowered for term in ("schedule", "remind", "calendar", "personal")):
        return "personal"
    return "system"


def _profile(cwd: str | Path, domain: str) -> TrustProfile:
    data = _read(cwd)
    return next((item for item in data["profiles"] if item.domain == domain), _default_profile(domain))


def _read(cwd: str | Path) -> dict[str, list]:
    profiles = [_default_profile(domain) for domain in DOMAINS]
    path = calibration_path(cwd)
    if not path.exists():
        return {"profiles": profiles, "signals": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"profiles": profiles, "signals": []}
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return {"profiles": profiles, "signals": []}
    profile_map = {item.domain: item for item in profiles}
    for item in data.get("profiles", []):
        if not isinstance(item, dict):
            continue
        try:
            domain = str(item.get("domain") or "")
            if domain in DOMAINS:
                profile_map[domain] = TrustProfile(
                    domain=domain,
                    initiative=max(0, min(5, int(item.get("initiative") or _default_initiative(domain)))),
                    ask_threshold=_risk(str(item.get("ask_threshold") or "high")),
                    notes=[_clean(note, 240) for note in item.get("notes", []) if str(note).strip()],
                    updated_at=int(item.get("updated_at") or 0),
                )
        except Exception:
            continue
    signals: list[TrustSignal] = []
    for item in data.get("signals", []):
        if not isinstance(item, dict):
            continue
        try:
            domain = str(item.get("domain") or "")
            if domain in DOMAINS:
                signals.append(
                    TrustSignal(
                        signal_id=str(item.get("signal_id") or ""),
                        domain=domain,
                        delta=max(-2, min(2, int(item.get("delta") or 0))),
                        text=_clean(item.get("text") or "", 500),
                        source=_clean(item.get("source") or "chat", 40),
                        created_at=int(item.get("created_at") or 0),
                    )
                )
        except Exception:
            continue
    return {"profiles": list(profile_map.values()), "signals": [signal for signal in signals if signal.signal_id]}


def _write(cwd: str | Path, profiles: list[TrustProfile], signals: list[TrustSignal]) -> None:
    path = calibration_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "profiles": [item.to_dict() for item in profiles], "signals": [item.to_dict() for item in signals]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _default_profile(domain: str) -> TrustProfile:
    return TrustProfile(domain=domain, initiative=_default_initiative(domain), ask_threshold="high", updated_at=0)


def _default_initiative(domain: str) -> int:
    return {
        "code": 4,
        "ui": 4,
        "business": 4,
        "research": 4,
        "memory": 4,
        "personal": 3,
        "external": 2,
        "finance": 1,
        "system": 3,
    }.get(domain, 3)


def _signal_delta(text: str, domain: str) -> int:
    if "ask before" in text.lower() or "ask first" in text.lower():
        return -2 if domain in {"external", "finance"} else -1
    if AUTONOMY_RE.search(text):
        return 1
    if CAUTION_RE.search(text):
        return -1
    return 0


def _signal_note(delta: int, text: str) -> str:
    prefix = "more initiative" if delta > 0 else "more confirmation"
    return f"{prefix}: {_clean(text, 140)}"


def _risk(value: str) -> str:
    clean = str(value or "medium").strip().lower()
    return clean if clean in RISKS else "medium"


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean(value, 240)
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _clean(value: object, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
