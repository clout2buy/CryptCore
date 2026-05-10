from __future__ import annotations

import os

from core import file_state

from .fs import clip, is_text_file, rel, resolve_read, within_root
from .types import Tool


# Bytes returned per call. 256KB is enough for most source files; long logs
# and big JSON should be sliced with offset/limit instead.
_DEFAULT_MAX = 256 * 1024


def _max_bytes() -> int:
    raw = os.getenv("CRYPT_READ_MAX_BYTES")
    if raw and raw.isdigit():
        return max(4 * 1024, int(raw))  # floor at 4KB so a typo doesn't break reads
    return _DEFAULT_MAX


def run(args: dict) -> str:
    path = resolve_read(args["path"])
    if not path.exists():
        raise FileNotFoundError(rel(path))
    if not path.is_file():
        raise IsADirectoryError(rel(path))
    if not is_text_file(path):
        raise ValueError(f"refusing to read binary file: {rel(path)}")

    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")

    raw_offset = args.get("offset")
    raw_limit = args.get("limit")
    sliced = bool(raw_offset or raw_limit)

    all_lines = text.splitlines(keepends=True)
    if sliced:
        start = max(1, int(raw_offset or 1)) - 1
        end = start + max(1, int(raw_limit)) if raw_limit else len(all_lines)
        slice_ = all_lines[start:end]
        first_line_no = start + 1
    else:
        slice_ = all_lines
        first_line_no = 1

    # Prefix line numbers so the model can reference precise locations.
    # Width of 6 fits files up to 999,999 lines. The "→" separator makes it
    # visually obvious that the leading number is metadata, not file content.
    numbered = "".join(
        f"{first_line_no + i:>6}→{line}" for i, line in enumerate(slice_)
    )

    max_bytes = _max_bytes()
    clipped = len(numbered) > max_bytes
    full_range = sliced and start == 0 and end >= len(all_lines)
    file_state.record_read(
        path,
        raw,
        offset=int(raw_offset) if raw_offset else None,
        limit=int(raw_limit) if raw_limit else None,
        partial=(sliced and not full_range) or clipped,
    )

    return clip(numbered, max_bytes)


def summary(args: dict) -> str:
    path = str(args.get("path", ""))
    offset = args.get("offset")
    limit = args.get("limit")
    if offset or limit:
        end = (offset or 1) + (limit or 0) - 1 if limit else "end"
        return f"{path} L{offset or 1}-{end}"
    return path


def classify(args: dict) -> str | None:
    path = str(args.get("path", ""))
    if not path:
        return None
    return "safe" if within_root(path) else "ask"


_PROMPT = """
Each output line is prefixed with `<lineno>→` for reference. The line number
and arrow are metadata added by the tool, NOT part of the file's contents.
When you call `edit_file`, pass the raw source text only — do not include
the line number prefix in `old` or `new`.

Use `offset` (1-indexed start line) + `limit` (line count) on long files
instead of asking for the whole thing.

For images or PDFs, use read_media instead; read_file intentionally returns
UTF-8 text only.
""".strip()


TOOL = Tool(
    "read_file",
    (
        "Read a UTF-8 text file. Relative paths resolve inside the workspace; "
        "absolute paths may point anywhere on disk. Returns line-numbered "
        "content. Pass `offset` (1-indexed start line) and `limit` (line count) "
        "to read a slice instead of the whole file. Refuses to read binary files."
    ),
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "1-indexed line to start from."},
            "limit": {"type": "integer", "description": "Number of lines to return."},
        },
        "required": ["path"],
    },
    "auto",
    run,
    prompt=_PROMPT,
    priority=20,
    summary=summary,
    classify=classify,
    parallel_safe=True,
)
