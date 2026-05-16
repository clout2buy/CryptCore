"""Lightweight intent routing for natural chat prompts."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class IntentRoute:
    intent: str
    route_role: str
    confidence: float
    rationale: str
    durable: bool = False
    needs_approval: bool = False
    needs_clarification: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


_INTENTS: list[tuple[str, str, str, tuple[str, ...], bool, bool]] = [
    ("external_action", "planner", "external state-changing action", ("post", "publish", "buy", "purchase", "email", "reddit", "tweet", "dm ", "send money", "create account"), True, True),
    ("business", "builder", "business or revenue outcome", ("business", "revenue", "income", "customers", "leads", "store", "product launch", "stripe", "sales funnel"), True, False),
    ("code", "builder", "software build or code change", ("code", "repo", "fix", "bug", "implement", "build", "refactor", "webui", "frontend", "backend", "runtime"), False, False),
    ("review", "reviewer", "review or verification request", ("review", "audit", "check my", "find bugs", "critique", "security", "verify", "tests"), False, False),
    ("research", "planner", "research or lookup request", ("research", "search", "find online", "look up", "latest", "compare", "source", "citations"), False, False),
    ("schedule", "planner", "scheduled follow-up or monitor", ("remind", "schedule", "every day", "daily", "weekly", "monitor", "watch", "keep an eye"), True, False),
    ("learn", "planner", "skill or learning request", ("learn this", "skill", "install skill", "teach yourself", "remember how", "incorporate"), True, False),
    ("browser", "planner", "browser operation", ("open browser", "website", "web page", "click", "form", "dashboard", "localhost"), False, False),
    ("desktop", "planner", "desktop operation", ("desktop", "screen", "mouse", "keyboard", "window", "screenshot"), False, False),
    ("file", "builder", "file or artifact work", ("file", "folder", "document", "spreadsheet", "presentation", "html", "markdown"), False, False),
]

_CHAT_STARTS = ("hi", "hey", "yo", "hello", "sup", "thanks", "thank you")
_CASUAL_MARKERS = (
    "idk",
    "lol",
    "lmao",
    "haha",
    "testing u",
    "testing you",
    "test you",
    "trying you",
)
_CODE_TEST_MARKERS = (
    "run test",
    "run tests",
    "write test",
    "write tests",
    "add test",
    "add tests",
    "unit test",
    "pytest",
    "vitest",
    "jest",
    "test suite",
    "failing test",
)


def route(text: str) -> IntentRoute:
    clean = " ".join(str(text or "").split())
    lower = clean.lower()
    words = re.findall(r"[a-z0-9']+", lower)
    if not clean:
        return IntentRoute("empty", "", 1.0, "empty prompt", needs_clarification=True)
    if len(words) <= 5 and any(lower == item or lower.startswith(f"{item} ") for item in _CHAT_STARTS):
        return IntentRoute("conversation", "", 0.92, "short conversational opener")
    if len(words) <= 8 and any(marker in lower for marker in _CASUAL_MARKERS):
        return IntentRoute("conversation", "", 0.88, "casual check-in")

    matches: list[tuple[int, str, str, str, bool, bool]] = []
    for intent, role, rationale, terms, durable, approval in _INTENTS:
        hits = sum(1 for term in terms if term in lower)
        if intent == "code" and any(marker in lower for marker in _CODE_TEST_MARKERS):
            hits += 1
        if hits:
            matches.append((hits, intent, role, rationale, durable, approval))
    if matches:
        hits, intent, role, rationale, durable, approval = sorted(matches, key=lambda item: item[0], reverse=True)[0]
        confidence = min(0.95, 0.62 + hits * 0.11 + (0.08 if len(words) >= 10 else 0.0))
        return IntentRoute(intent, role, confidence, rationale, durable=durable, needs_approval=approval)

    if len(words) >= 12:
        return IntentRoute("general_task", "planner", 0.58, "long request with no strong domain signal", durable=True)
    return IntentRoute("conversation", "", 0.68, "general conversation")


def prompt_hint(decision: IntentRoute) -> str:
    if decision.intent in {"conversation", "empty"}:
        return ""
    approval = " approval-gate external state changes" if decision.needs_approval else ""
    durable = " create or update a durable mission if this needs follow-through" if decision.durable else ""
    return (
        f"intent={decision.intent}; route={decision.route_role or 'auto'}; "
        f"confidence={decision.confidence:.2f}; {decision.rationale};{durable};{approval}"
    ).replace("; ;", ";").strip()
