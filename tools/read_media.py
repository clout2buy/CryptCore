from __future__ import annotations

import base64
import mimetypes
import os

from .fs import clip, rel, resolve_read, within_root
from .types import Tool


MAX_MEDIA_BYTES = 8 * 1024 * 1024
MAX_PDF_TEXT_CHARS = 220_000
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
DOCUMENT_TYPES = {"application/pdf"}


def run(args: dict):
    path = resolve_read(args["path"])
    if not path.exists():
        raise FileNotFoundError(rel(path))
    if not path.is_file():
        raise IsADirectoryError(rel(path))
    data = path.read_bytes()
    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    metadata = f"media: {rel(path)}\ntype: {media_type}\nbytes: {len(data)}"
    text_blocks = [{"type": "text", "text": metadata}]

    if media_type in DOCUMENT_TYPES:
        pdf_text = _extract_pdf_text(path)
        if pdf_text:
            text_blocks.append({
                "type": "text",
                "text": "\n\n--- extracted PDF text ---\n" + clip(pdf_text, MAX_PDF_TEXT_CHARS),
            })

    if len(data) > MAX_MEDIA_BYTES:
        if media_type in DOCUMENT_TYPES and len(text_blocks) > 1:
            return {
                "__crypt_tool_result__": True,
                "display": metadata + "\nembedded_media: skipped; file exceeds native media cap",
                "content": text_blocks,
            }
        raise ValueError(f"media file too large ({len(data)} bytes, max {MAX_MEDIA_BYTES})")

    encoded = base64.b64encode(data).decode("ascii")
    if media_type in IMAGE_TYPES:
        block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": encoded,
            },
        }
    elif media_type in DOCUMENT_TYPES:
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": encoded,
            },
        }
    else:
        raise ValueError(f"unsupported media type: {media_type}")
    return {
        "__crypt_tool_result__": True,
        "display": metadata,
        "content": [*text_blocks, block],
    }


def _extract_pdf_text(path) -> str:
    if os.getenv("CRYPT_PDF_TEXT", "1").strip().lower() in {"0", "false", "no", "off"}:
        return ""
    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    try:
        reader = PdfReader(str(path))
        chunks: list[str] = []
        for idx, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                chunks.append(f"--- PAGE {idx} ---\n{text}")
        return "\n\n".join(chunks)
    except Exception:
        return ""


def summary(args: dict) -> str:
    return str(args.get("path", ""))


def classify(args: dict) -> str | None:
    path = str(args.get("path", ""))
    if not path:
        return None
    return "safe" if within_root(path) else "ask"


TOOL = Tool(
    "read_media",
    (
        "Read an image or PDF. Relative paths resolve inside the workspace; "
        "absolute paths may point anywhere on disk. PDFs include extracted text "
        "when pypdf is installed."
    ),
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    },
    "auto",
    run,
    priority=25,
    summary=summary,
    classify=classify,
    parallel_safe=True,
)
