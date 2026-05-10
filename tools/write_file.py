from __future__ import annotations

import difflib

from core import artifact_lifecycle, file_state

from .fs import rel, resolve
from .types import Tool


def run(args: dict) -> str:
    path = resolve(args["path"])
    content = str(args["content"])
    _assert_complete_preview_artifact(path, content)
    overwrite = bool(args.get("overwrite"))
    existed = path.exists()
    if existed and not overwrite:
        raise FileExistsError(
            "file exists; pass overwrite=true to replace it, or use edit_file"
        )
    if existed:
        file_state.assert_fresh_for_edit(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    file_state.record_write(path)
    artifact_lifecycle.record_write(path)
    return f"{'overwrote' if existed else 'created'} {rel(path)}"


def _assert_complete_preview_artifact(path, content: str) -> None:
    suffix = path.suffix.lower()
    lowered = content.lower()
    if suffix in {".html", ".htm"} and "<html" in lowered and "</html>" not in lowered:
        raise ValueError(
            "incomplete HTML artifact: content opens an <html> document but is missing </html>. "
            "Retry with the complete file content or split the implementation into smaller complete files."
        )
    if suffix == ".svg" and "<svg" in lowered and "</svg>" not in lowered:
        raise ValueError(
            "incomplete SVG artifact: content opens an <svg> document but is missing </svg>. "
            "Retry with the complete file content."
        )


def summary(args: dict) -> str:
    p = str(args.get("path", ""))
    if args.get("overwrite"):
        return f"{p} (overwrite)"
    return p


def preview(args: dict) -> str:
    """For new files: show a head/tail snippet of the content. For
    overwrites: show the unified diff between current and proposed."""
    try:
        path = resolve(args["path"])
        new_content = str(args.get("content", ""))
        label = rel(path)
        if path.exists() and path.is_file():
            try:
                old = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                old = ""
            diff = list(difflib.unified_diff(
                old.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{label}",
                tofile=f"b/{label}",
                n=2,
                lineterm="",
            ))
            return "".join(diff[2:]).rstrip() if diff else ""
        # New file — render as all-additions so the diff renderer colors it.
        lines = new_content.splitlines() or [""]
        head = lines[:30]
        body = "\n".join(f"+{ln}" for ln in head)
        if len(lines) > 30:
            body += f"\n+ ... +{len(lines) - 30} more line(s)"
        return f"+++ b/{label}\n{body}"
    except Exception:
        return ""


TOOL = Tool(
    "write_file",
    (
        "Create a new UTF-8 text file inside the workspace. By default refuses "
        "to overwrite — use edit_file for existing files. Pass overwrite=true "
        "ONLY when you really want to replace the entire file content (rare; "
        "edit_file is almost always the right tool for changes)."
    ),
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "overwrite": {
                "type": "boolean",
                "description": "If true, replace existing file content instead of erroring.",
            },
        },
        "required": ["path", "content"],
    },
    "ask",
    run,
    priority=50,
    summary=summary,
    preview=preview,
)
