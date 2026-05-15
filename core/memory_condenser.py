"""Condense Crypt memory into durable context and discardable noise."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import memory_journal


PROMOTE_TYPES = {"preference", "persona", "project-fact", "tool-quirk", "recurring", "business"}
STALE_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class CondenseResult:
    path: Path
    promoted: int = 0
    kept: int = 0
    discarded: int = 0
    merged: int = 0
    notes: tuple[str, ...] = ()


def condense(cwd: str | Path, *, now: int | None = None, max_working: int = 35) -> CondenseResult:
    """Promote important working context and drop stale weak signals."""
    path = memory_journal.ensure_journal(cwd)
    state = memory_journal._read_state() or memory_journal._empty_state(cwd)  # noqa: SLF001 - same package layer
    current = int(time.time()) if now is None else int(now)
    working, merged_working = _merge_duplicates([item for item in state.get("working", []) if isinstance(item, dict)])
    long_term, merged_long_term = _merge_duplicates([item for item in state.get("long_term", []) if isinstance(item, dict)])
    merged_count = merged_working + merged_long_term

    promoted: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    discarded: list[dict[str, Any]] = []
    notes: list[str] = []

    for item in working:
        item_type = str(item.get("memory_type") or item.get("category") or "memory")
        confidence = float(item.get("confidence") or 0.0)
        age = max(0, current - int(item.get("updated_at") or item.get("created_at") or current))
        if item_type in PROMOTE_TYPES or confidence >= 0.75:
            promoted_item = dict(item)
            promoted_item["confidence"] = min(1.0, max(confidence, 0.76) + 0.02)
            promoted_item["decay"] = "stable" if item_type in {"preference", "persona", "project-fact"} else "long"
            promoted_item["updated_at"] = current
            promoted_item["tags"] = memory_journal._dedupe([*(item.get("tags") or []), "condensed"])  # noqa: SLF001
            promoted.append(promoted_item)
            notes.append(f"promoted {item_type}: {str(item.get('text') or '')[:90]}")
        elif age >= STALE_SECONDS and confidence < 0.55:
            discarded.append(item)
        else:
            kept.append(item)

    if promoted or discarded or merged_count or len(kept) > max_working:
        state["long_term"] = memory_journal._trim(_dedupe_long_term([*promoted, *long_term]), memory_journal.MAX_LONG_TERM)  # noqa: SLF001
        state["working"] = memory_journal._trim(kept, max_working)  # noqa: SLF001
        state["schema"] = memory_journal.SCHEMA_VERSION
        state["updated_at"] = current
        memory_journal._write_state(state)  # noqa: SLF001
        memory_journal._write_markdown(state)  # noqa: SLF001

    return CondenseResult(
        path=path,
        promoted=len(promoted),
        kept=min(len(kept), max_working),
        discarded=len(discarded) + max(0, len(kept) - max_working),
        merged=merged_count,
        notes=tuple(notes[:8]),
    )


def _merge_duplicates(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    by_key: dict[str, dict[str, Any]] = {}
    merged = 0
    for item in items:
        key = memory_journal._fingerprint(str(item.get("text") or ""))  # noqa: SLF001
        if not key:
            continue
        if key not in by_key:
            by_key[key] = dict(item)
            continue
        merged += 1
        by_key[key] = _merge_two(by_key[key], item)
    rows = list(by_key.values())
    rows.sort(key=lambda item: int(item.get("updated_at") or 0), reverse=True)
    return rows, merged


def _dedupe_long_term(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _merge_duplicates(items)[0]


def _merge_two(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    first = dict(a)
    second = dict(b)
    if int(second.get("updated_at") or 0) > int(first.get("updated_at") or 0):
        first, second = second, first
    first["hits"] = int(first.get("hits") or 1) + int(second.get("hits") or 1)
    first["confidence"] = max(float(first.get("confidence") or 0.0), float(second.get("confidence") or 0.0))
    first["tags"] = memory_journal._dedupe([*(first.get("tags") or []), *(second.get("tags") or [])])  # noqa: SLF001
    first["corrections"] = [*(first.get("corrections") or []), *(second.get("corrections") or [])][:8]
    if not first.get("importance") and second.get("importance"):
        first["importance"] = second["importance"]
    return first
