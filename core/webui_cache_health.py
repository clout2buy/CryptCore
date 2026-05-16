"""Expected browser cache contract and repair actions for the WebUI."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CacheStore:
    key: str
    label: str
    version: str
    required: bool
    max_items: int = 0
    repair_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


STORES = (
    CacheStore(
        "crypt.webui.chatSessions.v2",
        "Browser Chat Sessions",
        "v2",
        True,
        max_items=30,
        repair_action="Backup corrupt value to *.corrupt.<timestamp>, then remove the active key.",
    ),
    CacheStore("crypt.composer.advanced", "Composer Mode", "v1", False, repair_action="Remove key to restore simple composer."),
    CacheStore("crypt.voice.output.enabled", "Voice Output Toggle", "v1", False, repair_action="Remove key to disable stuck speech output."),
    CacheStore("crypt.voice.output.voice", "Voice Selection", "v1", False, repair_action="Remove key to use default Kokoro voice."),
)


def snapshot() -> dict[str, Any]:
    stores = [store.to_dict() for store in STORES]
    return {
        "schema": SCHEMA_VERSION,
        "total": len(stores),
        "required": sum(1 for store in STORES if store.required),
        "stores": stores,
        "repairActions": [store.repair_action for store in STORES if store.repair_action],
        "clientHealth": "reported-by-browser",
    }


def assess_client(report: dict[str, Any]) -> dict[str, Any]:
    issues = []
    for store in STORES:
        item = report.get(store.key) if isinstance(report, dict) else None
        if store.required and not item:
            issues.append({"key": store.key, "severity": "warning", "detail": "required browser cache store missing"})
        if isinstance(item, dict) and item.get("corrupt"):
            issues.append({"key": store.key, "severity": "warning", "detail": "browser reported corrupt cache"})
        if store.max_items and isinstance(item, dict) and int(item.get("count") or 0) > store.max_items:
            issues.append({"key": store.key, "severity": "warning", "detail": f"too many cached items: {item.get('count')}"})
    return {
        "status": "warning" if issues else "ok",
        "issues": issues,
    }
