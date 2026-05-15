"""Safe rebuild/restart planning for the local Crypt runtime."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import session, settings


SCHEMA_VERSION = 1
WATCH_DIRS = ("core", "tools")
WATCH_FILES = ("main.py", "launch_crypt_webui.bat")


@dataclass(frozen=True)
class RebuildPlan:
    reason: str
    commands: list[str]
    restart_command: str
    preserve: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RebuildRecord:
    rebuild_id: str
    status: str
    reason: str = ""
    checks: list[str] = field(default_factory=list)
    restart_recommended: bool = False
    backend_changed_at: int = 0
    created_at: int = 0


def state_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "runtime" / "rebuilds.json"


def plan(cwd: str | Path, *, reason: str = "", changed_files: list[str] | None = None) -> RebuildPlan:
    root = Path(cwd).expanduser().resolve()
    launch = root / "launch_crypt_webui.bat"
    restart_command = str(launch if launch.exists() else "python main.py webui --host 127.0.0.1 --port 8765")
    return RebuildPlan(
        reason=_clean(reason or "Local runtime changed; verify before restart.", 300),
        commands=[
            "python -m py_compile core\\*.py",
            "node --check core\\webui_static\\app.js",
            "scripts\\verify_core.ps1 -Quick",
        ],
        restart_command=restart_command,
        preserve=[
            "Browser chat sessions stay in localStorage.",
            "Backend sessions remain under the project session directory.",
            "Memory, missions, agents, skills, and settings are durable under the Crypt app data directory.",
        ],
        changed_files=[_rel(root, Path(item)) for item in changed_files or []],
        notes=[
            "Do not restart while a task is actively streaming.",
            "Run focused tests first when the change touches a narrow module.",
            "Use the launch BAT to reopen the browser/backend after verification.",
        ],
    )


def record(
    cwd: str | Path,
    *,
    status: str,
    reason: str = "",
    checks: list[str] | None = None,
    restart_recommended: bool | None = None,
) -> RebuildRecord:
    root = Path(cwd).expanduser().resolve()
    changed_at = backend_changed_at(root)
    record_item = RebuildRecord(
        rebuild_id="rebuild_" + time.strftime("%Y%m%d_%H%M%S"),
        status=_clean(status or "recorded", 40),
        reason=_clean(reason, 300),
        checks=[_clean(item, 220) for item in checks or [] if str(item).strip()],
        restart_recommended=bool(changed_at) if restart_recommended is None else bool(restart_recommended),
        backend_changed_at=changed_at,
        created_at=_now(),
    )
    records = [record_item, *list_records(root, limit=100)]
    _write(root, records)
    return record_item


def list_records(cwd: str | Path, *, limit: int = 20) -> list[RebuildRecord]:
    records = _read(cwd)
    records.sort(key=lambda item: item.created_at, reverse=True)
    return records[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    records = list_records(cwd, limit=5)
    changed_at = backend_changed_at(cwd)
    last = records[0] if records else None
    restart_recommended = bool(last and changed_at and changed_at > last.created_at)
    return {
        "path": str(state_path(cwd)),
        "backendChangedAt": changed_at,
        "restartRecommended": restart_recommended,
        "lastRecord": asdict(last) if last else None,
        "plan": asdict(plan(cwd, reason="Runtime rebuild plan.")),
        "history": [asdict(item) for item in records],
    }


def prompt_section(cwd: str | Path) -> str:
    data = snapshot(cwd)
    if not data["restartRecommended"]:
        return ""
    plan_data = data["plan"]
    return (
        "# Live Runtime Rebuild\n"
        "- Backend files changed after the last rebuild record; recommend focused verification before restart.\n"
        f"- Restart command: {plan_data['restart_command']}\n"
        f"- Checks: {'; '.join(plan_data['commands'])}"
    )


def backend_changed_at(cwd: str | Path) -> int:
    root = Path(cwd).expanduser().resolve()
    latest = 0
    for name in WATCH_FILES:
        latest = max(latest, _mtime(root / name))
    for dirname in WATCH_DIRS:
        directory = root / dirname
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".py", ".js", ".css", ".html", ".json"}:
                latest = max(latest, _mtime(path))
    return latest


def _read(cwd: str | Path) -> list[RebuildRecord]:
    path = state_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return []
    out: list[RebuildRecord] = []
    for item in data.get("records", []):
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                RebuildRecord(
                    rebuild_id=str(item.get("rebuild_id") or ""),
                    status=str(item.get("status") or "recorded"),
                    reason=str(item.get("reason") or ""),
                    checks=[str(value) for value in item.get("checks", []) if str(value).strip()],
                    restart_recommended=bool(item.get("restart_recommended")),
                    backend_changed_at=int(item.get("backend_changed_at") or 0),
                    created_at=int(item.get("created_at") or 0),
                )
            )
        except Exception:
            continue
    return [item for item in out if item.rebuild_id]


def _write(cwd: str | Path, records: list[RebuildRecord]) -> None:
    path = state_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "records": [asdict(item) for item in records[:100]]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _mtime(path: Path) -> int:
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


def _rel(root: Path, path: Path) -> str:
    try:
        resolved = path if path.is_absolute() else root / path
        return str(resolved.resolve().relative_to(root))
    except (OSError, ValueError):
        return str(path)


def _clean(value: object, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
