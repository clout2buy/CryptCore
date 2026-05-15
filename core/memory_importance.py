"""Importance scoring for passive memory candidates."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


PREFERENCE_RE = re.compile(r"\b(always|never|prefer|i want|i need|crypt should|i like|i hate|tone|persona|homie)\b", re.I)
PROJECT_RE = re.compile(r"\b(repo|project|workspace|file|folder|path|bug|ui|business|revenue|customer|website|mission|agent|skill|model|provider)\b", re.I)
RISK_RE = re.compile(r"\b(emails?|phone|password|token|api key|credential|payment|address|legal|medical|finance|money)\b|@", re.I)
FUTURE_RE = re.compile(r"\b(next|todo|to do|follow up|remember|track|monitor|daily|weekly|every time|launch|build|fix|update)\b", re.I)


@dataclass(frozen=True)
class ImportanceScore:
    total: float
    confidence: float
    promote: bool
    recurrence: float = 0.0
    preference: float = 0.0
    project_value: float = 0.0
    risk: float = 0.0
    future_usefulness: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_text(text: str, *, category: str = "", previous_hits: int = 0) -> ImportanceScore:
    clean = " ".join(str(text or "").split())
    words = clean.split()
    reasons: list[str] = []
    base = 0.22
    recurrence = min(0.18, max(0, previous_hits) * 0.06)
    preference = _component(PREFERENCE_RE, clean, 0.24, "preference", reasons)
    project_value = _component(PROJECT_RE, clean, 0.22, "project value", reasons)
    risk = _component(RISK_RE, clean, 0.16, "sensitive or high-risk fact", reasons)
    future = _component(FUTURE_RE, clean, 0.18, "future usefulness", reasons)
    if len(words) >= 18:
        future = max(future, 0.10)
        reasons.append("substantial context")
    if category in {"persona", "business", "project"}:
        project_value = max(project_value, 0.18)
        reasons.append(f"{category} category")
    if previous_hits:
        reasons.append(f"repeated {previous_hits + 1} time(s)")
    total = min(1.0, base + recurrence + preference + project_value + risk + future)
    promote = total >= 0.68 or preference >= 0.2 or (project_value >= 0.18 and future >= 0.12) or risk >= 0.16
    confidence = min(0.95, 0.42 + total * 0.55)
    return ImportanceScore(
        total=round(total, 4),
        confidence=round(confidence, 4),
        promote=promote,
        recurrence=round(recurrence, 4),
        preference=round(preference, 4),
        project_value=round(project_value, 4),
        risk=round(risk, 4),
        future_usefulness=round(future, 4),
        reasons=_dedupe(reasons),
    )


def _component(pattern: re.Pattern[str], text: str, value: float, reason: str, reasons: list[str]) -> float:
    if pattern.search(text):
        reasons.append(reason)
        return value
    return 0.0


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out[:8]
