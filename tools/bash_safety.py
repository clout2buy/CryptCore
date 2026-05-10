"""Lightweight static analysis for shell commands.

We use this to decide:
- "safe"   : read-only, run without prompting
- "danger" : destructive, prompt with a warning even in yolo
- "ask"    : default, take the existing approval path

Parsing real shells is undecidable, so we keep the rules conservative:
shell metacharacters that change control flow (`|`, `;`, `&&`, `||`, `>`,
`>>`, `<`, backticks, `$()`) disqualify a command from "safe" entirely.
The "danger" detector is regex-based and runs regardless of metachars,
so something like `foo && rm -rf /` still flags as danger.
"""
from __future__ import annotations

import re

# Commands whose only effect is process/system inspection. File-content
# readers such as cat/type/Get-Content are intentionally excluded because
# operand parsing is shell-specific and can otherwise bypass workspace
# approval/secret boundaries.
_SAFE_LEAD: frozenset[str] = frozenset({
    # POSIX-y
    "ls", "pwd", "whoami", "id", "which",
    "echo", "printf",
    "wc", "file", "stat",
    "du", "df", "ps", "uname", "date", "uptime", "hostname",
    "tree",
    "true", "false",
    # Windows cmd / PowerShell read-onlys
    "dir", "where", "ver",
    "get-childitem", "get-location", "get-process",
})

# git subcommands that never mutate the repo regardless of ordinary args.
_SAFE_GIT_ALWAYS: frozenset[str] = frozenset({
    "status", "diff", "log", "show", "blame",
    "rev-parse", "ls-files", "ls-tree", "describe",
})

# Regexes for clearly destructive operations. Each entry is (pattern, reason).
# Patterns are case-insensitive and matched anywhere in the command, so they
# fire even inside a chained command like `make && rm -rf build`.
_DANGER: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b"),
     "rm -rf can wipe directories irreversibly"),
    (re.compile(r"\brm\s+(-[a-zA-Z]*r)\s+/\s*(?!\S)"),
     "rm -r on root filesystem"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"),
     "git reset --hard discards uncommitted work"),
    (re.compile(r"\bgit\s+push\s+(--force\b|-f\b|--force-with-lease\b)"),
     "git push --force can overwrite remote history"),
    (re.compile(r"\bgit\s+commit\s+--amend\b"),
     "git commit --amend rewrites the previous commit"),
    (re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*[fxd]"),
     "git clean removes untracked files"),
    (re.compile(r"\bgit\s+checkout\s+(--|\.)"),
     "git checkout -- discards local changes"),
    (re.compile(r"\bgit\s+restore\s+(--source|--worktree|\.)"),
     "git restore can overwrite local changes"),
    (re.compile(r"\bgit\s+branch\s+-D\b"),
     "git branch -D force-deletes a branch"),
    (re.compile(r"\bdd\s+.*\bof=/dev/"),
     "dd to a device file is irreversible"),
    (re.compile(r"\bmkfs\b"),
     "mkfs formats a filesystem"),
    (re.compile(r"\bshred\b"),
     "shred destroys file contents"),
    (re.compile(r"\bchmod\s+-R\b"),
     "chmod -R can lock you out of files"),
    (re.compile(r"\bsudo\s+rm\b"),
     "sudo rm escalates a delete"),
    # Windows-flavored
    (re.compile(r"\b(del|erase)\s+/[a-zA-Z]*[sq]", re.IGNORECASE),
     "del /s/q recursively deletes"),
    (re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE),
     "format wipes a drive"),
    (re.compile(r"\bremove-item\s+.*-recurse\b", re.IGNORECASE),
     "Remove-Item -Recurse deletes a tree"),
    (re.compile(r"\brmdir\s+/s\b", re.IGNORECASE),
     "rmdir /s recursively deletes"),
    # Curl/wget piped to a shell — classic supply-chain footgun
    (re.compile(r"\bcurl\b[^|]*\|\s*(sh|bash|zsh|powershell)\b"),
     "piping a downloaded script to a shell runs untrusted code"),
    (re.compile(r"\bwget\b[^|]*\|\s*(sh|bash|zsh|powershell)\b"),
     "piping a downloaded script to a shell runs untrusted code"),
]

# Anything in here means "this command has side-channels we can't reason about"
# and disqualifies the whole pipeline from being "safe". We still let the
# danger regex fire — it just prevents a false "safe" verdict.
_UNSAFE_META = re.compile(r"[|;`]|&&|\|\||>>?|<|\$\(")


def is_destructive(command: str) -> str | None:
    """Return a human-readable reason if `command` looks destructive, else None."""
    for pat, reason in _DANGER:
        if pat.search(command):
            return reason
    return None


def is_read_only(command: str) -> bool:
    """True only if every leading verb in the command is in the read-only set
    AND there are no shell metacharacters that could re-route output."""
    cmd = command.strip()
    if not cmd:
        return False
    if _UNSAFE_META.search(cmd):
        return False
    parts = cmd.split()
    if not parts:
        return False
    lead = parts[0].lower()
    # Strip an env-var prefix like `FOO=bar git status`. Keep it simple.
    while "=" in lead and lead == parts[0].lower() and len(parts) > 1 and "=" in parts[0]:
        parts = parts[1:]
        lead = parts[0].lower() if parts else ""

    if not lead:
        return False
    if lead == "git":
        return _is_read_only_git(parts[1:])
    return lead in _SAFE_LEAD


def _is_read_only_git(args: list[str]) -> bool:
    if not args:
        return False
    sub = args[0].lower()
    rest = [a.lower() for a in args[1:]]
    if sub in _SAFE_GIT_ALWAYS:
        return True
    if sub == "branch":
        return not rest or all(
            a in {"-a", "-r", "-v", "-vv", "--all", "--remotes", "--list"}
            for a in rest
        )
    if sub == "remote":
        return not rest or rest == ["-v"] or (rest and rest[0] in {"show", "get-url"})
    if sub == "config":
        return bool(rest) and rest[0] in {"--get", "--get-all", "--get-regexp", "--list", "-l"}
    if sub == "tag":
        return not rest or rest[0] in {"-l", "--list", "-n"}
    if sub == "stash":
        return bool(rest) and rest[0] in {"list", "show"}
    return False


def classify(command: str) -> str | None:
    """Single entry point used by bash.py.

    Returns "danger", "safe", or None (= "ask"). Danger wins over safe so
    a command like `ls && rm -rf /tmp/x` gets flagged.
    """
    if is_destructive(command):
        return "danger"
    if is_read_only(command):
        return "safe"
    return None


# ---- not reached at runtime; kept here so the patterns are easy to eyeball ----
__all__ = ["classify", "is_destructive", "is_read_only"]
