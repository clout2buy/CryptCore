"""Workspace filesystem helpers shared across tools.

Workspace root comes from the CRYPT_ROOT env var (set by core.runtime).
Mutating and scanning tools funnel through `resolve()` which refuses paths
that escape the workspace. Explicit read-only tools can use `resolve_read()`
so user-supplied absolute files are usable without switching workspace.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator


SKIP_DIRS = {
    # VCS
    ".git", ".hg", ".svn",
    # Python
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env", ".tox", ".eggs",
    # Editors
    ".idea", ".vscode", ".vs",
    # JS / TS
    "node_modules", "bower_components",
    ".next", ".nuxt", ".svelte-kit", ".turbo",
    ".parcel-cache",
    # Build / dist
    "dist", "build", "out", "target",
    # Misc caches
    ".cache", ".gradle", ".terraform",
}

BINARY_EXTS = {
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".svg",
    # Audio / video
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".webm", ".avi", ".mov", ".mkv",
    # Archives
    ".zip", ".tar", ".gz", ".rar", ".7z", ".bz2", ".xz", ".zst",
    # Documents
    ".pdf", ".docx", ".xlsx", ".pptx",
    # Native binaries
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".obj",
    ".class", ".jar", ".war", ".pyc", ".pyo",
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # Data
    ".db", ".sqlite", ".sqlite3", ".mdb",
    ".pkl", ".npy", ".npz", ".bin", ".dat",
}

MAX_TEXT_BYTES = 5_000_000  # 5MB cap on file reads / scans


def root() -> Path:
    try:
        from core import runtime

        context_root = runtime.context_cwd()
        if context_root:
            return Path(context_root).resolve()
    except Exception:
        pass
    return Path(os.getenv("CRYPT_ROOT", ".")).resolve()


def resolve(path: str) -> Path:
    base = root()
    p = Path(path).expanduser()
    p = p if p.is_absolute() else base / p
    p = p.resolve()
    try:
        p.relative_to(base)
    except ValueError as e:
        raise PermissionError(f"path outside workspace: {path}") from e
    return p


def resolve_read(path: str) -> Path:
    """Resolve a read-only path.

    Relative paths stay anchored under the current workspace. Absolute paths
    and `~` paths are allowed because users often hand Crypt a one-off PDF,
    image, log, or config file outside the active project.
    """
    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return resolve(path)


def within_root(path: str | Path) -> bool:
    base = root()
    p = Path(path).expanduser()
    p = p if p.is_absolute() else base / p
    try:
        p.resolve().relative_to(base)
        return True
    except (OSError, ValueError):
        return False


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(root()))
    except ValueError:
        return str(path)


def is_text_file(path: Path, sniff_bytes: int = 4096) -> bool:
    """Detect whether a file is plain text. Cheap heuristic, no chardet."""
    if path.suffix.lower() in BINARY_EXTS:
        return False
    try:
        with path.open("rb") as f:
            chunk = f.read(sniff_bytes)
    except OSError:
        return False
    if not chunk:
        return True
    if b"\x00" in chunk:
        return False
    # Allow common control bytes (tab, newline, CR, escape, etc.) plus printable.
    allowed = set(range(0x20, 0x100)) | {7, 8, 9, 10, 11, 12, 13, 27}
    non_text = sum(1 for b in chunk if b not in allowed)
    return non_text / len(chunk) <= 0.30


def all_files(path: Path) -> Iterator[Path]:
    """Yield every file under `path`, skipping junk directories. Paths only —
    no size or text check, so binaries and big files still appear. Use this
    for listing/glob operations where the contents aren't read."""
    items = [path] if path.is_file() else path.rglob("*")
    for item in items:
        if not item.is_file():
            continue
        if any(part in SKIP_DIRS for part in item.parts):
            continue
        yield item


def text_files(path: Path, max_size: int = MAX_TEXT_BYTES) -> Iterator[Path]:
    """Yield text files under `path`, skipping junk dirs, oversized files,
    and binaries. Use this for scans that read file contents (grep, etc.)."""
    for item in all_files(path):
        try:
            if item.stat().st_size > max_size:
                continue
        except OSError:
            continue
        if not is_text_file(item):
            continue
        yield item


# Backward-compat alias: callers that imported `files` keep working with the
# stricter (text-only) behaviour. New code should pick all_files / text_files.
files = text_files


def clip(text: str, limit: int = 12000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


def int_arg(args: dict, name: str, default: int, cap: int) -> int:
    return max(1, min(int(args.get(name) or default), cap))
