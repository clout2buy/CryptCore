"""User-defined allow/deny rules for tool calls.

Lives at ``~/.crypt/permissions.json``. Format:

    {
      "allow": ["bash:git status*", "bash:rg *", "edit_file:*"],
      "deny":  ["bash:rm -rf *", "bash:git push --force*"]
    }

Each rule is `<tool_name>:<glob>` where the glob matches the tool's
user-facing summary string (the same text shown in the approval prompt).
Globs use `*` and `?` only — no regex, no nested globs. Match is case
sensitive and anchored to the start of the summary.

Precedence:
1. Deny rule match  -> reject (returned as tool failure)
2. Allow rule match -> skip prompt entirely (overrides danger)
3. Otherwise        -> fall through to existing classify/permission logic

Inspired by Gemini CLI / Qwen Code's "always approve this exact thing"
flow but kept dead simple — no scopes, no project overrides, no UI editor.
Edit the JSON in your editor of choice and restart Crypt.
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

from .settings import APP_DIR


PERMISSIONS_PATH = APP_DIR / "permissions.json"


@dataclass
class Rules:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)

    def matches_allow(self, key: str) -> str | None:
        return _first_match(key, self.allow)

    def matches_deny(self, key: str) -> str | None:
        return _first_match(key, self.deny)


_CACHE: Rules | None = None
_CACHE_MTIME: float | None = None


def load(path: Path | None = None) -> Rules:
    """Load rules from disk with mtime-based caching. Edits to the file
    take effect on the next dispatch — no restart required."""
    global _CACHE, _CACHE_MTIME

    path = path or PERMISSIONS_PATH
    if not path.exists():
        _CACHE = Rules()
        _CACHE_MTIME = None
        return _CACHE

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return _CACHE or Rules()

    if _CACHE is not None and _CACHE_MTIME == mtime:
        return _CACHE

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Bad JSON shouldn't break dispatch — degrade to no rules and let
        # the doctor surface it on the next /doctor.
        _CACHE = Rules()
        _CACHE_MTIME = mtime
        return _CACHE

    rules = Rules(
        allow=[str(r) for r in (data.get("allow") or []) if r],
        deny=[str(r) for r in (data.get("deny") or []) if r],
    )
    _CACHE = rules
    _CACHE_MTIME = mtime
    return rules


def check(tool_name: str, summary: str) -> tuple[str, str | None]:
    """Resolve a tool call against the user's rules.

    Returns one of:
      ("deny",    "<rule>")  - reject the call with this rule string
      ("allow",   "<rule>")  - skip prompts; explicit user approval
      ("default", None)      - no opinion; let classify/permission decide
    """
    rules = load()
    key = f"{tool_name}:{summary or ''}"

    deny_match = rules.matches_deny(key)
    if deny_match:
        return "deny", deny_match
    allow_match = rules.matches_allow(key)
    if allow_match:
        return "allow", allow_match
    return "default", None


def _first_match(key: str, patterns: list[str]) -> str | None:
    for pat in patterns:
        # fnmatch is shell-glob style: *, ?, [seq]. Anchored implicitly.
        if fnmatch.fnmatchcase(key, pat):
            return pat
    return None


def write_example(path: Path | None = None) -> Path:
    """Drop a commented example file at ~/.crypt/permissions.json so users
    can see the format. Only writes if the file does not exist."""
    path = path or PERMISSIONS_PATH
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    example = {
        "_comment": (
            "Allow rules skip the approval prompt for matching tool calls. "
            "Deny rules reject them outright. Format: '<tool>:<summary glob>'. "
            "The summary is the same text shown in the approval prompt."
        ),
        "allow": [
            "bash:git status*",
            "bash:git diff*",
            "bash:git log*",
            "bash:ls *",
            "bash:cat *",
        ],
        "deny": [
            "bash:rm -rf /*",
            "bash:git push --force*",
        ],
    }
    path.write_text(json.dumps(example, indent=2), encoding="utf-8")
    return path
