"""Regex search over workspace files.

Prefers ripgrep (`rg`) if it's on PATH for real performance on real repos.
Falls back to a pure-Python implementation otherwise so the tool still works
on a fresh box. The user-facing schema is the same either way.
"""
from __future__ import annotations

import re
import shutil
import subprocess

from .fs import files, int_arg, rel, resolve, root
from .types import Tool


_RG = shutil.which("rg")


def run(args: dict) -> str:
    pattern = args["pattern"]
    path = str(args.get("path", "."))
    limit = int_arg(args, "limit", 100, 500)
    case_insensitive = bool(args.get("case_insensitive", False))
    glob = args.get("glob")

    if _RG:
        out = _run_rg(pattern, path, limit, case_insensitive, glob)
        if out is not None:
            return out
    return _run_python(pattern, path, limit, case_insensitive, glob)


def _run_rg(
    pattern: str,
    path: str,
    limit: int,
    case_insensitive: bool,
    glob: str | None,
) -> str | None:
    target = resolve(path)
    cmd = [_RG, "--no-heading", "--line-number", "--color", "never", "--max-count", str(limit)]
    if case_insensitive:
        cmd.append("-i")
    if glob:
        cmd.extend(["--glob", str(glob)])
    cmd.extend(["-e", pattern, "--", str(target)])

    try:
        r = subprocess.run(
            cmd,
            cwd=root(),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None  # fall back to Python

    # rg exit codes: 0 = matches, 1 = no matches, 2 = error.
    if r.returncode == 1:
        return "(no matches)"
    if r.returncode != 0:
        # rg reported a real error (bad regex, unreadable path). Surface it
        # rather than silently falling back — the model needs to know.
        msg = (r.stderr or "").strip() or f"rg exited {r.returncode}"
        raise RuntimeError(f"rg: {msg}")

    lines = r.stdout.splitlines()[:limit]
    if not lines:
        return "(no matches)"

    rel_lines = [_normalize_rg_line(line) for line in lines]
    return "\n".join(rel_lines)


def _normalize_rg_line(line: str) -> str:
    """rg emits absolute paths because we passed an absolute target. Make them
    workspace-relative to match the Python fallback's output shape."""
    base = str(root()).replace("\\", "/")
    line = line.replace("\\", "/")
    if line.startswith(base + "/"):
        return line[len(base) + 1:]
    return line


def _run_python(
    pattern: str,
    path: str,
    limit: int,
    case_insensitive: bool,
    glob: str | None,
) -> str:
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        raise RuntimeError(f"invalid regex: {e}") from e

    glob_re = _glob_to_regex(glob) if glob else None
    matches: list[str] = []
    for fp in files(resolve(path)):
        if glob_re and not glob_re.search(rel(fp).replace("\\", "/")):
            continue
        try:
            lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if compiled.search(line):
                matches.append(f"{rel(fp)}:{i}: {line.strip()}")
                if len(matches) >= limit:
                    return "\n".join(matches)
    return "\n".join(matches) or "(no matches)"


def _glob_to_regex(glob: str) -> re.Pattern:
    """Tiny glob → regex for `**`, `*`, `?`. Matches anywhere in the path."""
    out: list[str] = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "*" and i + 1 < len(glob) and glob[i + 1] == "*":
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out))


def summary(args: dict) -> str:
    suffix = " (i)" if args.get("case_insensitive") else ""
    g = args.get("glob")
    glob_part = f" glob={g}" if g else ""
    return f"{args.get('pattern', '')!r} in {args.get('path', '.')}{glob_part}{suffix}"


_PROMPT = """
Regex search over the workspace. Uses ripgrep when available, falls back to
pure Python. Pass `glob` (e.g. `**/*.py`) to scope the search. Pass
`case_insensitive: true` for ASCII case-folding.
""".strip()


TOOL = Tool(
    "grep",
    "Regex search inside workspace files. Uses ripgrep when available.",
    {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "limit": {"type": "integer"},
            "case_insensitive": {"type": "boolean"},
            "glob": {
                "type": "string",
                "description": "Glob filter for paths, e.g. **/*.py",
            },
        },
        "required": ["pattern"],
    },
    "auto",
    run,
    prompt=_PROMPT,
    priority=30,
    summary=summary,
    parallel_safe=True,
)
