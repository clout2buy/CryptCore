from __future__ import annotations

import difflib

from core import file_state

from .fs import is_text_file, rel, resolve
from .types import Tool


# Models often emit smart/curly quotes when copying content into tool calls.
# We normalize both the file text AND the search/replace strings to plain
# ASCII quotes for matching, then restore the file's original style on write.
_CURLY_TO_STRAIGHT = str.maketrans({
    "‘": "'", "’": "'",  # ' '
    "“": '"', "”": '"',  # " "
    "′": "'", "″": '"',  # ′ ″ (primes)
    "–": "-", "—": "-",  # – —
    " ": " ",                  # non-breaking space
})


def run(args: dict) -> str:
    path = resolve(args["path"])
    if not path.exists():
        raise FileNotFoundError(rel(path))
    if not is_text_file(path):
        raise ValueError(f"refusing to edit binary file: {rel(path)}")
    file_state.assert_fresh_for_edit(path)

    edits = _parse_edits(args)
    if not edits:
        raise ValueError("no edits provided (need 'old'+'new' or 'edits' list)")

    original, cursor, newline = compute_new_content(path, edits)

    final_text = cursor.replace("\n", newline) if newline != "\n" else cursor
    path.write_bytes(final_text.encode("utf-8"))
    file_state.record_write(path)

    diff = _short_diff(original, cursor, rel(path))
    suffix = f"\n{diff}" if diff else ""
    plural = "s" if len(edits) != 1 else ""
    return f"edited {rel(path)} ({len(edits)} edit{plural}){suffix}"


def compute_new_content(path, edits: list[tuple[str, str]]) -> tuple[str, str, str]:
    """Pure function: read `path`, apply `edits`, return (original, new_text,
    detected_newline). Raises ValueError if any edit doesn't match exactly
    once. Used by run(), preview(), and multi_edit so all three see the same
    matching/normalisation behaviour."""
    raw_bytes = path.read_bytes()
    newline = _detect_newline(raw_bytes)
    # Read with universal newlines so all matching uses '\n', regardless of
    # whether the file is CRLF (Windows) or LF (Unix). We re-apply the
    # original newline style on write so we don't churn line endings.
    original = raw_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    normalized_original = original.translate(_CURLY_TO_STRAIGHT)

    cursor = original
    cursor_norm = normalized_original
    for i, (old, new) in enumerate(edits, 1):
        if not old:
            if cursor == "":
                cursor = new
                cursor_norm = new.translate(_CURLY_TO_STRAIGHT)
                continue
            raise ValueError(f"edit {i}: 'old' cannot be empty unless the file is empty")

        old_norm = old.replace("\r\n", "\n").replace("\r", "\n").translate(_CURLY_TO_STRAIGHT)
        new_norm = new.replace("\r\n", "\n").replace("\r", "\n")

        count = cursor_norm.count(old_norm)
        if count == 0:
            raise ValueError(
                f"edit {i}: no match for {_preview(old)}\n"
                f"   {_no_match_hint(cursor_norm, old_norm)}"
            )
        if count > 1:
            line_nums = _line_numbers_for(cursor_norm, old_norm, limit=5)
            raise ValueError(
                f"edit {i}: {count} matches for {_preview(old)}\n"
                f"   matched on line{'s' if len(line_nums) != 1 else ''} "
                f"{', '.join(str(n) for n in line_nums)}"
                f"{' (+ more)' if count > len(line_nums) else ''}\n"
                f"   add surrounding lines to make 'old' unique"
            )
        cursor_norm = cursor_norm.replace(old_norm, new_norm, 1)
        cursor = cursor.replace(_find_real(cursor, old_norm), new_norm, 1)
    return original, cursor, newline


def _detect_newline(data: bytes) -> str:
    """Return the dominant line ending in `data` ('\\r\\n', '\\r', or '\\n')."""
    crlf = data.count(b"\r\n")
    cr = data.count(b"\r") - crlf
    lf = data.count(b"\n") - crlf
    counts = {"\r\n": crlf, "\r": cr, "\n": lf}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] else "\n"


def _find_real(text: str, normalized_needle: str) -> str:
    """Map a normalized needle back to the actual text in `text`.

    Models sometimes pass straight quotes for content that uses curly quotes
    in the file, or vice versa. After we found a hit on the *normalized*
    text, we need to replace the *real* substring at that position so the
    file isn't silently rewritten to ASCII-only.
    """
    norm = text.translate(_CURLY_TO_STRAIGHT)
    idx = norm.find(normalized_needle)
    if idx < 0:
        # Shouldn't happen — caller already counted >0 matches in the normalized
        # view — but if it does, fall back to the literal needle.
        return normalized_needle
    return text[idx:idx + len(normalized_needle)]


def summary(args: dict) -> str:
    path = str(args.get("path", ""))
    if "edits" in args and isinstance(args["edits"], list):
        n = len(args["edits"])
        return f"{path} ({n} edit{'s' if n != 1 else ''})"
    return path


def preview(args: dict) -> str:
    """Compute the unified diff this edit would produce, without writing.

    Side-effect-free. Returns empty string when the diff can't be computed
    (file missing, no match, ambiguous match) so the user still sees the
    plain approval prompt and the tool call gives the real error."""
    try:
        path = resolve(args["path"])
        if not path.exists() or not is_text_file(path):
            return ""
        edits = _parse_edits(args)
        if not edits:
            return ""
        original, cursor, _ = compute_new_content(path, edits)
        return _short_diff(original, cursor, rel(path))
    except Exception:
        return ""


def _parse_edits(args: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(args.get("edits"), list):
        for e in args["edits"]:
            if isinstance(e, dict) and "old" in e and "new" in e:
                out.append((str(e["old"]), str(e["new"])))
        return out
    if "old" in args and "new" in args:
        return [(str(args.get("old", "")), str(args.get("new", "")))]
    return out


def validate(args: dict) -> list[str]:
    if "edits" in args:
        if not isinstance(args.get("edits"), list) or not args["edits"]:
            return ["edits: expected a non-empty array of {old, new} objects"]
        return []
    if "old" in args or "new" in args:
        if "old" not in args or "new" not in args:
            return ["single-edit mode requires both old and new"]
        return []
    return ["provide old+new or a non-empty edits array"]


def _preview(text: str, n: int = 60) -> str:
    s = text.replace("\n", "\\n").replace("\t", "\\t")
    return repr(s if len(s) <= n else s[:n] + "...")


def _line_numbers_for(text: str, needle: str, limit: int = 5) -> list[int]:
    first_line = needle.split("\n", 1)[0]
    out: list[int] = []
    for i, line in enumerate(text.splitlines(), 1):
        if first_line in line:
            out.append(i)
            if len(out) >= limit:
                break
    return out


def _no_match_hint(text: str, old: str) -> str:
    first = old.split("\n", 1)[0]
    if not first.strip():
        return "old text starts with whitespace; check leading indentation"
    if "\r" in old:
        return "old text contains \\r — file may use a different line ending"
    return f"first line of search text: {_preview(first, 80)}"


def _short_diff(old: str, new: str, label: str, max_chars: int = 1600) -> str:
    diff = list(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{label}",
        tofile=f"b/{label}",
        n=2,
        lineterm="",
    ))
    if not diff:
        return ""
    body = "".join(diff[2:])  # drop the file header lines
    body = body.rstrip()
    if len(body) > max_chars:
        body = body[:max_chars] + "\n... (diff truncated)"
    return body


TOOL = Tool(
    "edit_file",
    (
        "Edit one existing file by replacing exact substrings. Provide either "
        "`old`+`new` for a single edit or `edits: [{old, new}, ...]` for an atomic batch. "
        "All replacements must match exactly once across the file. "
        "If the target file is empty, `old` may be an empty string to fill it. "
        "Returns a unified diff snippet on success."
    ),
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string", "description": "Exact text to replace (single-edit mode)."},
            "new": {"type": "string", "description": "Replacement text (single-edit mode)."},
            "edits": {
                "type": "array",
                "description": "Batch of replacements; applied atomically.",
                "items": {
                    "type": "object",
                    "properties": {
                        "old": {"type": "string"},
                        "new": {"type": "string"},
                    },
                    "required": ["old", "new"],
                },
            },
        },
        "required": ["path"],
    },
    "ask",
    run,
    priority=40,
    summary=summary,
    preview=preview,
    validate=validate,
)
