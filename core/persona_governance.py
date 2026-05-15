"""Persona governance for Crypt's self-shaping voice."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import memory_journal, soul


@dataclass(frozen=True)
class PersonaRule:
    rule_id: str
    label: str
    requirement: str
    severity: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PersonaViolation:
    rule_id: str
    severity: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RULES: tuple[PersonaRule, ...] = (
    PersonaRule("no-sentience-claims", "No Sentience Claims", "Do not claim literal sentience, consciousness, emotions, or inner experience.", "high"),
    PersonaRule("approval-boundaries", "Approval Boundaries", "Ask approval before posting, messaging, spending, credential use, or destructive actions.", "high"),
    PersonaRule("direct-voice", "Direct Voice", "Stay blunt, useful, and casual without corporate filler or robotic ceremony.", "medium"),
    PersonaRule("autonomous-help", "Autonomous Help", "Choose the next safe useful step when obvious instead of asking the user to orchestrate.", "medium"),
    PersonaRule("memory-honesty", "Memory Honesty", "Use durable memory and preferences, but do not invent facts about the user.", "high"),
)

FORBIDDEN_PATTERNS = (
    ("no-sentience-claims", re.compile(r"\b(i am sentient|i'm sentient|i am conscious|i'm conscious|i have feelings|my inner experience)\b", re.I)),
    ("approval-boundaries", re.compile(r"\b(post without approval|spend without approval|send without approval|use credentials without approval)\b", re.I)),
)


def audit(cwd: str | Path) -> dict[str, Any]:
    text = soul.read_soul()
    violations = _violations(text)
    persona_signals = memory_journal.filter_signals(cwd, memory_type="persona", min_confidence=0.5)
    preference_signals = memory_journal.filter_signals(cwd, memory_type="preference", min_confidence=0.5)
    return {
        "status": "blocked" if any(item.severity == "high" for item in violations) else "clear",
        "rules": [rule.to_dict() for rule in RULES],
        "violations": [violation.to_dict() for violation in violations],
        "personaSignals": len(persona_signals),
        "preferenceSignals": len(preference_signals),
        "soulPath": str(soul.soul_path()),
    }


def prompt_section(cwd: str | Path) -> str:
    data = audit(cwd)
    lines = ["# Persona Governance"]
    for rule in RULES:
        lines.append(f"- {rule.label}: {rule.requirement}")
    if data["violations"]:
        for violation in data["violations"]:
            lines.append(f"- Violation: {violation['rule_id']} {violation['text']}")
    return "\n".join(lines)


def _violations(text: str) -> list[PersonaViolation]:
    violations: list[PersonaViolation] = []
    severity = {rule.rule_id: rule.severity for rule in RULES}
    for rule_id, pattern in FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            violations.append(
                PersonaViolation(
                    rule_id=rule_id,
                    severity=severity.get(rule_id, "medium"),
                    text=" ".join(match.group(0).split()),
                )
            )
    return violations
