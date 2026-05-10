from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from core import redact
from core.settings import restrict_file_permissions

from .bash_safety import classify as _classify_command, is_destructive
from .fs import int_arg, root
from .types import Tool


# Search utilities exit with code 1 when they simply found nothing — that's
# not a failure, just a useful "no" answer. Treat exit 1 as success when the
# command's leading verb matches one of these.
_NO_MATCH_OK = re.compile(r"^\s*(grep|egrep|fgrep|rg|ack|find|locate)\b")

# Cap on bytes returned to the model per stream. Mirrors Claude Code's
# bash-output policy: enough to see the shape of a build but small enough
# that one big test run can't blow the context. Full output spills to disk.
_STREAM_CAP = 30_000
_SPILL_DIR = Path.home() / ".crypt" / "runs"

# POSIX command -> Windows cmd equivalent. Used to warn the model when it
# uses a Unix verb on cmd.exe so it can re-issue the right command without
# burning a turn on a cryptic "(no output)" failure.
_POSIX_HINTS = {
    "wc": "use PowerShell: `(Get-Content file).Count` or `Get-ChildItem ... | Measure-Object -Line`",
    "ls": "use `dir` (cmd) or `Get-ChildItem` (PowerShell)",
    "cat": "use `type` (cmd) or `Get-Content` (PowerShell)",
    "grep": "use `findstr` (cmd) or `Select-String` (PowerShell), or install ripgrep",
    "head": "use `more` (cmd) or `Get-Content -Head N` (PowerShell)",
    "tail": "use `Get-Content -Tail N` (PowerShell)",
    "which": "use `where` (cmd) or `Get-Command` (PowerShell)",
    "rm": "use `del` / `rmdir /s` (cmd) or `Remove-Item` (PowerShell)",
    "mv": "use `move` / `ren` (cmd) or `Move-Item` (PowerShell)",
    "cp": "use `copy` (cmd) or `Copy-Item` (PowerShell)",
    "touch": "use `type nul > file` (cmd) or `New-Item file` (PowerShell)",
    "df": "use `Get-PSDrive` (PowerShell)",
    "du": "use `Get-ChildItem ... | Measure-Object -Sum Length` (PowerShell)",
    "ps": "use `tasklist` (cmd) or `Get-Process` (PowerShell)",
    "kill": "use `taskkill` (cmd) or `Stop-Process` (PowerShell)",
    "uname": "use `systeminfo` (cmd) or `$PSVersionTable` (PowerShell)",
    "env": "use `set` (cmd) or `Get-ChildItem env:` (PowerShell)",
    "export": "use `set VAR=value` (cmd) or `$env:VAR='value'` (PowerShell)",
    "sed": "use `(Get-Content file) -replace 'old','new' | Set-Content file` (PowerShell), or use edit_file",
    "awk": "use PowerShell pipelines, or use grep + python",
    "true": "use `cmd /c exit 0` or `$true` (PowerShell)",
    "false": "use `cmd /c exit 1` or `$false` (PowerShell)",
}

# Glob-bearing characters cmd.exe never expands. If the model writes a
# command with these AND a verb like wc/cat/grep that needs them expanded,
# we know cmd.exe will pass the literal `*` to the program and it will fail.
_GLOB_HINT_RE = re.compile(r"[*?]")


def run(args: dict) -> str:
    command = args["command"]
    run_command, stdin = _prepare_command(command)
    try:
        r = subprocess.run(
            run_command,
            shell=True,
            cwd=root(),
            input=stdin,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            # Default 30s, capped at 10 minutes so `pip install` and friends fit.
            timeout=int_arg(args, "timeout", 30, 600),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"command timed out after {e.timeout}s. "
            f"Re-run with a larger `timeout` arg, or use bash_start for long jobs."
        ) from None

    body, spill = _format_output(command, r.stdout or "", r.stderr or "")

    if r.returncode != 0:
        # grep/find returning 1 is "no match", not an error. Pass through cleanly
        # so the model sees the truth instead of an alarming exception.
        if r.returncode == 1 and _NO_MATCH_OK.match(command):
            return body if body != "(no output)" else "(no matches)"
        # Errors: full body (already capped + spilled) so the model sees what
        # was attempted AND the failure message. Add diagnosis hints so a
        # cryptic "(no output)" exit becomes actionable.
        hint = _diagnose_failure(command, r.returncode, r.stdout or "", r.stderr or "")
        suffix = f"\n[full output: {spill}]" if spill else ""
        msg = f"exit {r.returncode}\n{body}{suffix}"
        if hint:
            msg += f"\n[hint: {hint}]"
        raise RuntimeError(msg)
    return body


def _prepare_command(command: str) -> tuple[str, str | None]:
    heredoc = _extract_simple_heredoc(command)
    if heredoc is not None:
        return heredoc
    return command, None


def _extract_simple_heredoc(command: str) -> tuple[str, str] | None:
    """Translate the common POSIX heredoc stdin pattern for Windows cmd.exe.

    Models often emit:

        python - <<'PY'
        ...
        PY

    `cmd.exe` treats `<<` as invalid syntax. For a single heredoc on the
    first line, strip the heredoc operator and pass the body as stdin. This
    preserves useful multiline Python without changing normal shell behavior.
    """
    normalized = command.replace("\r\n", "\n")
    if "\n" not in normalized or "<<" not in normalized:
        return None

    first, rest = normalized.split("\n", 1)
    match = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][\w.-]*)\1\s*$", first)
    if not match:
        return None

    tag = match.group(2)
    prefix = first[:match.start()].rstrip()
    if not prefix:
        return None

    lines = rest.split("\n")
    end_idx = None
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip() == tag:
            end_idx = idx
            break
    if end_idx is None:
        return None

    body = "\n".join(lines[:end_idx])
    if body and not body.endswith("\n"):
        body += "\n"
    return prefix, body


def _diagnose_failure(command: str, returncode: int, stdout: str, stderr: str) -> str:
    """Best-effort hint when the failure has no useful output. Always returns
    a string ('' if nothing helpful to say) — never raises."""
    try:
        captured = (stdout + stderr).strip()
        first_word = re.match(r"^\s*([A-Za-z_][\w.-]*)", command)
        verb = (first_word.group(1) if first_word else "").lower()

        # Windows + POSIX verb mismatch is the most common cause of
        # "(no output) exit 1" we'll ever see.
        if os.name == "nt" and verb in _POSIX_HINTS:
            installed = shutil.which(verb)
            if not installed:
                return f"`{verb}` is a POSIX command not installed on this Windows shell. {_POSIX_HINTS[verb]}"
            if _GLOB_HINT_RE.search(command):
                return (
                    f"`{verb}` is installed, but cmd.exe does not expand globs (*). "
                    f"Wrap the command in `bash -c '...'` if Git Bash is on PATH, "
                    f"or use PowerShell: {_POSIX_HINTS[verb]}"
                )

        if os.name == "nt" and re.search(r"[A-Za-z]:\\{2,}", command):
            return (
                "Windows shell paths should use single backslashes. JSON escaping "
                "is not shell syntax; use C:\\Users\\Name\\file, not C:\\\\Users\\\\Name\\\\file."
            )

        # Generic empty-output diagnosis.
        if not captured:
            redirect = re.search(r"\b2>\s*(?:nul|/dev/null|&1)?", command)
            if redirect:
                return (
                    "command exited non-zero with no captured output because stderr "
                    "was redirected (2>nul or 2>/dev/null). Drop the redirect to see why."
                )
            if os.name == "nt" and verb and not shutil.which(verb):
                return f"`{verb}` was not found on PATH. Check spelling or use a PowerShell equivalent."
            if verb and not shutil.which(verb):
                return f"`{verb}` was not found on PATH. Check spelling or install it."
        return ""
    except Exception:
        return ""


def _format_output(command: str, stdout: str, stderr: str) -> tuple[str, str]:
    """Cap stdout/stderr to ~30 KB each. If anything overflows, spill the
    full streams to ~/.crypt/runs/<id>.log and point the model at the path.

    Returns (body_for_model, spill_path_or_empty).
    """
    parts: list[str] = []
    overflow = False
    if stdout.strip():
        head, did_clip = _clip_stream(stdout)
        overflow = overflow or did_clip
        parts.append(head)
    if stderr.strip():
        head, did_clip = _clip_stream(stderr)
        overflow = overflow or did_clip
        parts.append(f"[stderr]\n{head}")
    body = "\n".join(parts) if parts else "(no output)"

    if not overflow:
        return body, ""

    spill = _write_spill(command, stdout, stderr)
    # Forward-slash the path even on Windows — cleaner in tool output and
    # readable by every shell we'd hand it to.
    pretty = spill.replace("\\", "/") if spill else ""
    return body + f"\n[output truncated; full log: {pretty}]", pretty


def _clip_stream(text: str, cap: int = _STREAM_CAP) -> tuple[str, bool]:
    """Keep head + tail of a stream so the model sees both the start and the
    failure message. Returns (clipped, was_truncated)."""
    text = text.rstrip()
    if len(text) <= cap:
        return text, False
    half = cap // 2
    head = text[:half].rstrip()
    tail = text[-half:].lstrip()
    omitted = len(text) - len(head) - len(tail)
    return f"{head}\n... [{omitted:,} chars truncated]\n{tail}", True


def _write_spill(command: str, stdout: str, stderr: str) -> str:
    try:
        _SPILL_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.log"
        path = _SPILL_DIR / name
        with path.open("w", encoding="utf-8", errors="replace") as f:
            f.write(f"$ {redact.text(command)}\n\n")
            if stdout:
                f.write(redact.text(stdout))
                if not stdout.endswith("\n"):
                    f.write("\n")
            if stderr:
                f.write("\n[stderr]\n")
                f.write(redact.text(stderr))
                if not stderr.endswith("\n"):
                    f.write("\n")
        restrict_file_permissions(path)
        return str(path)
    except OSError:
        return ""


def classify(args: dict) -> str | None:
    cmd = str(args.get("command", ""))
    return _classify_command(cmd)


def summary(args: dict) -> str:
    cmd = str(args.get("command", ""))
    reason = is_destructive(cmd)
    label = cmd[:120]
    return f"!{label}  ({reason})" if reason else label


_PROMPT = """
For shell work. Crypt classifies commands at runtime:
- system-inspection commands (`ls`, `pwd`, `git status`, `git diff/log/show`,
  `python -V`, etc.) auto-approve in every mode.
- file-content readers (`cat`, `type`, `Get-Content`, `env`, `printenv`) are
  approval-gated; prefer `read_file`, `grep`, or `read_media` so workspace and
  secret boundaries are enforced consistently.
- destructive commands (`rm -rf`, `git reset --hard`, `git push --force`,
  `git commit --amend`, `git clean`, `dd`, etc.) prompt with a warning even
  in yolo. Don't try to outsmart this — use the dedicated tools when they
  exist (`edit_file` instead of `sed -i`, etc.).
- `grep`/`find` returning exit 1 means "no matches" — that's success.

## Platform notes

On Windows, `bash` runs `cmd.exe`. cmd.exe DOES NOT expand globs (`*`, `?`)
the way POSIX shells do, and POSIX commands like `wc`, `cat`, `head`,
`tail`, `sed`, `awk`, `which`, `ps`, `df`, `du` are usually NOT installed.
Crypt supports the common single-heredoc stdin pattern (`python - <<'PY'`)
as a compatibility shim, but prefer short `python -c "..."` commands or
write a temporary script when quoting gets complex.
Prefer:
- `dir` / `findstr` / `where` (cmd built-ins)
- `Get-ChildItem` / `Select-String` / `Measure-Object`
  via `powershell -Command "..."`
- ripgrep (`rg`) when installed — works the same on every platform.

When a command fails with no output, the harness adds a `[hint: ...]`
line explaining what likely went wrong. Don't redirect stderr to null
(`2>nul`, `2>/dev/null`) — it suppresses the actual error.
""".strip()


TOOL = Tool(
    "bash",
    "Run a shell command from the workspace. On Windows this uses cmd.exe.",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {
                "type": "integer",
                "description": "Seconds before the process is killed (default 30, max 600).",
            },
        },
        "required": ["command"],
    },
    "ask",
    run,
    prompt=_PROMPT,
    priority=60,
    summary=summary,
    classify=classify,
)
