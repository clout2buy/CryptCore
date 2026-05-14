"""Infer durable missions from ordinary chat."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import goals, redact


ACTION_TERMS = {
    "build",
    "create",
    "launch",
    "start",
    "make",
    "ship",
    "run",
    "operate",
    "manage",
    "monitor",
    "track",
    "watch",
    "grow",
    "sell",
    "post",
    "upgrade",
    "reverse engineer",
    "research",
    "find leads",
    "learn",
    "automate",
}

OUTCOME_TERMS = {
    "business",
    "income",
    "revenue",
    "customers",
    "leads",
    "website",
    "web site",
    "app",
    "tool",
    "agent",
    "workflow",
    "campaign",
    "store",
    "product",
    "game",
    "server",
    "reddit",
    "email",
    "brand",
    "content",
}

CADENCE_TERMS = {
    "daily": "daily",
    "every day": "daily",
    "each day": "daily",
    "weekly": "weekly",
    "every week": "weekly",
    "each week": "weekly",
    "monthly": "monthly",
    "every month": "monthly",
    "keep an eye": "daily",
    "keep track": "daily",
    "monitor": "daily",
    "watch": "daily",
    "track": "daily",
}

EXPLICIT_MISSION_TERMS = {
    "autonomous",
    "atonomous",
    "automatically",
    "on its own",
    "without me",
    "do it all",
    "mission",
    "keep going",
    "long term",
    "follow through",
}

ONE_OFF_STARTS = (
    "hi",
    "hey",
    "yo",
    "hello",
    "thanks",
    "thank you",
    "what is ",
    "who is ",
    "when is ",
    "where is ",
)

STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "i",
    "it",
    "me",
    "my",
    "of",
    "on",
    "please",
    "the",
    "to",
    "u",
    "you",
}


@dataclass(frozen=True)
class MissionDecision:
    created: bool
    goal: goals.Goal | None = None
    reason: str = ""
    duplicate: bool = False

    @property
    def prompt_hint(self) -> str:
        if not self.goal:
            return ""
        action = "created" if self.created else "matched existing"
        return (
            f"{action} autonomous mission '{self.goal.title}' ({self.goal.goal_id}); "
            "treat it as the durable outcome tracker, choose the next safe step, "
            "and do not ask the user to manage missions manually"
        )


def observe(workspace: str | Path, text: str) -> MissionDecision:
    """Create or reuse a mission when the chat asks for durable follow-through."""
    clean = _clean(text)
    if not _should_create(clean):
        return MissionDecision(False, reason="conversation does not need a durable mission")

    title = _title(clean)
    existing = _find_existing(workspace, title, clean)
    if existing:
        return MissionDecision(False, existing, reason="matching mission already exists", duplicate=True)

    cadence = _cadence(clean)
    tags = _tags(clean)
    goal = goals.add_goal(
        title,
        description=clean,
        workspace=workspace,
        success_metric=_success_metric(clean),
        cadence=cadence,
        priority=_priority(clean),
        tags=tags,
    )
    return MissionDecision(True, goal, reason="chat requested durable autonomous work")


def _should_create(text: str) -> bool:
    lower = text.lower()
    words = re.findall(r"[a-z0-9']+", lower)
    if len(words) <= 3 and any(lower == item or lower.startswith(f"{item} ") for item in ONE_OFF_STARTS):
        return False
    if any(lower.startswith(item) for item in ONE_OFF_STARTS) and len(words) <= 6:
        return False

    explicit = any(term in lower for term in EXPLICIT_MISSION_TERMS)
    cadence = any(term in lower for term in CADENCE_TERMS)
    actions = [term for term in ACTION_TERMS if term in lower]
    outcomes = [term for term in OUTCOME_TERMS if term in lower]
    multi_step = len(words) >= 8 and bool(actions) and bool(outcomes)
    complex_request = len(words) >= 14 and bool(actions)
    return explicit or cadence or multi_step or complex_request


def _title(text: str) -> str:
    lower = text.lower()
    if "business" in lower and any(term in lower for term in {"start", "launch", "create", "build"}):
        detail = _after_marker(text, "business")
        suffix = f": {detail}" if detail else ""
        return _limit(f"Build and operate the business{suffix}")
    if any(term in lower for term in {"monitor", "track", "watch", "keep an eye"}):
        return _limit(f"Monitor {_object_phrase(text)}")
    if "agent" in lower and any(term in lower for term in {"create", "make", "build", "learn"}):
        return _limit("Create and train the agent")

    sentence = re.split(r"[.!?\n]", text, maxsplit=1)[0]
    sentence = re.sub(
        r"^(ok|okay|alright|so|yo|hey|can you|could you|please|i want you to|i need you to|i want|i need|make it so|have it)\s+",
        "",
        sentence,
        flags=re.IGNORECASE,
    )
    sentence = sentence.strip(" ,:-")
    if not sentence:
        sentence = "Autonomous mission"
    return _limit(sentence[:1].upper() + sentence[1:])


def _object_phrase(text: str) -> str:
    for marker in ("keep an eye on", "keep track of", "tracking", "track", "monitor", "watch"):
        match = re.search(rf"\b{re.escape(marker)}\b(.*)$", text, flags=re.IGNORECASE)
        if match:
            phrase = match.group(1).strip(" :,-")
            if phrase:
                return phrase
    return "the ongoing outcome"


def _after_marker(text: str, marker: str) -> str:
    lower = text.lower()
    index = lower.find(marker)
    if index < 0:
        return ""
    phrase = text[index + len(marker):].strip(" :,-")
    phrase = re.sub(r"\b(and|then|while)\b.*$", "", phrase, flags=re.IGNORECASE).strip(" ,:-")
    return phrase


def _success_metric(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in {"income", "revenue", "sales", "profit"}):
        return "Income, expenses, next actions, and blockers stay tracked with review notes."
    if any(term in lower for term in {"monitor", "track", "watch", "keep an eye"}):
        return "Latest status is checked and summarized without manual prompting."
    if "business" in lower:
        return "Offer, launch assets, operations, and measurable revenue path are kept moving."
    if any(term in lower for term in {"website", "app", "tool"}):
        return "A working version is shipped, verified, and improved through follow-up."
    return "The requested outcome is planned, tracked, executed, and reviewed."


def _cadence(text: str) -> str:
    lower = text.lower()
    for marker, cadence in CADENCE_TERMS.items():
        if marker in lower:
            return cadence
    return ""


def _priority(text: str) -> int:
    lower = text.lower()
    if any(term in lower for term in {"business", "income", "revenue", "launch", "ship", "autonomous"}):
        return 4
    return 3


def _tags(text: str) -> list[str]:
    lower = text.lower()
    tags = ["auto", "mission", "chat"]
    if "business" in lower or any(term in lower for term in {"income", "revenue", "sales", "profit"}):
        tags.append("business")
    if any(term in lower for term in {"monitor", "track", "watch", "keep an eye"}):
        tags.append("monitor")
    if any(term in lower for term in {"build", "create", "make", "ship", "website", "app", "tool"}):
        tags.append("build")
    if any(term in lower for term in {"agent", "learn", "skill"}):
        tags.append("agent")
    return tags


def _find_existing(workspace: str | Path, title: str, text: str) -> goals.Goal | None:
    title_fp = _fingerprint(title)
    text_fp = _fingerprint(text)
    for goal in goals.list_goals(workspace, include_all=True):
        goal_fp = _fingerprint(f"{goal.title} {goal.description}")
        if not goal_fp:
            continue
        if title_fp and (title_fp == goal_fp or title_fp in goal_fp or goal_fp in title_fp):
            return goal
        if _overlap(text_fp, goal_fp) >= 0.60:
            return goal
    return None


def _fingerprint(text: str) -> set[str]:
    return {
        _stem(word)
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 2 and word not in STOP_WORDS
    }


def _stem(word: str) -> str:
    if word in {"daily", "weekly", "monthly"}:
        return {"daily": "day", "weekly": "week", "monthly": "month"}[word]
    if word.endswith("ing") and len(word) > 6:
        return word[:-3]
    if word.endswith("ies") and len(word) > 5:
        return f"{word[:-3]}y"
    if word.endswith("s") and len(word) > 4 and not word.endswith("ss"):
        return word[:-1]
    return word


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


def _clean(text: str) -> str:
    return " ".join(redact.text(str(text or "")).split())


def _limit(text: str, limit: int = 76) -> str:
    clean = " ".join(text.split()).strip(" .")
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."
