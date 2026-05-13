"""Install, list, and remove local Crypt skills."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from . import settings, skills


LOCK_FILE = "skills-lock.json"


def format_list(cwd: str | Path, *, include_disabled: bool = True) -> str:
    found = skills.discover(cwd, include_disabled=include_disabled)
    if not found:
        return "no skills found"
    lines: list[str] = []
    for skill in found:
        state = "enabled" if skill.enabled else f"blocked: {skill.blocked_reason}"
        desc = skill.description or skill.title or "(no description)"
        lines.append(f"${skill.name} [{state}] - {desc}\n  {skill.path}")
    return "\n".join(lines)


def install(
    source: str,
    *,
    cwd: str | Path,
    names: list[str] | None = None,
    global_scope: bool = False,
    use_upstream_cli: bool = False,
    yes: bool = False,
) -> str:
    source = str(source or "").strip()
    if not source:
        raise ValueError("skill source is required")
    if use_upstream_cli or _looks_remote(source):
        return _install_with_upstream_cli(source, names=names, global_scope=global_scope, yes=yes, cwd=cwd)
    return _install_local(Path(source).expanduser(), cwd=cwd, names=names, global_scope=global_scope)


def remove(name: str, *, cwd: str | Path, global_scope: bool = False) -> str:
    safe = skills._safe_name(name)  # Reuse the runtime skill-name sanitizer.
    root = _install_root(cwd, global_scope=global_scope)
    target = root / safe
    try:
        resolved = target.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise PermissionError(f"refusing to remove skill outside root: {target}") from exc
    if not target.exists():
        return f"skill not installed: {safe}"
    if target.is_symlink() or target.is_file():
        target.unlink()
    else:
        shutil.rmtree(target)
    _update_lock(root, safe, removed=True)
    return f"removed skill: {safe}"


def _install_local(
    source: Path,
    *,
    cwd: str | Path,
    names: list[str] | None,
    global_scope: bool,
) -> str:
    source = source.resolve()
    candidates = _candidate_skill_files(source)
    if names:
        wanted = {skills._safe_name(name).lower() for name in names}
        candidates = [path for path in candidates if _skill_name(path).lower() in wanted]
    if not candidates:
        raise FileNotFoundError(f"no SKILL.md files found in {source}")
    root = _install_root(cwd, global_scope=global_scope)
    root.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for skill_file in candidates:
        name = _skill_name(skill_file)
        dest = root / name
        if dest.exists():
            raise FileExistsError(f"skill already exists: {dest}")
        shutil.copytree(skill_file.parent, dest)
        _update_lock(
            root,
            name,
            source=str(source),
            path=str(skill_file.parent),
            hash=_folder_hash(dest),
        )
        installed.append(name)
    scope = "global" if global_scope else "project"
    return f"installed {len(installed)} {scope} skill(s): " + ", ".join(f"${name}" for name in installed)


def _install_with_upstream_cli(
    source: str,
    *,
    names: list[str] | None,
    global_scope: bool,
    yes: bool,
    cwd: str | Path,
) -> str:
    if shutil.which("npx") is None:
        raise RuntimeError("npx is not on PATH; install Node.js or install from a local skill folder")
    cmd = ["npx", "skills", "add", source, "-a", "codex"]
    if global_scope:
        cmd.append("-g")
    for name in names or []:
        cmd.extend(["--skill", name])
    if yes:
        cmd.append("-y")
    result = subprocess.run(
        cmd,
        cwd=str(Path(cwd).expanduser().resolve()),
        capture_output=True,
        text=True,
        timeout=600,
    )
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = "\n".join(item for item in (out, err) if item).strip()
        raise RuntimeError(detail or f"skills CLI failed with exit {result.returncode}")
    detail = "\n".join(item for item in (out, err) if item).strip()
    return detail or "skills CLI completed"


def _candidate_skill_files(source: Path) -> list[Path]:
    if source.is_file() and source.name == skills.SKILL_FILE:
        return [source]
    if source.is_dir() and (source / skills.SKILL_FILE).exists():
        return [source / skills.SKILL_FILE]
    if source.is_dir():
        return sorted(source.glob(f"*/{skills.SKILL_FILE}"))
    return []


def _skill_name(skill_file: Path) -> str:
    parsed = skills._parse_skill(skill_file)
    if not parsed.enabled:
        raise ValueError(f"skill blocked by safety scan: {parsed.name}: {parsed.blocked_reason}")
    return parsed.name


def _install_root(cwd: str | Path, *, global_scope: bool) -> Path:
    if global_scope:
        return settings.APP_DIR / "skills"
    return Path(cwd).expanduser().resolve() / ".agents" / "skills"


def _folder_hash(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        h.update(rel.encode("utf-8", errors="replace"))
        h.update(b"\0")
        try:
            h.update(path.read_bytes())
        except OSError:
            continue
        h.update(b"\0")
    return h.hexdigest()


def _update_lock(root: Path, name: str, *, removed: bool = False, **values: str) -> None:
    path = root / LOCK_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("skills", {})
    if not isinstance(data["skills"], dict):
        data["skills"] = {}
    if removed:
        data["skills"].pop(name, None)
    else:
        data["skills"][name] = {
            "installed_at": int(time.time()),
            **values,
        }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _looks_remote(source: str) -> bool:
    return (
        source.startswith("http://")
        or source.startswith("https://")
        or source.startswith("git@")
        or ("/" in source and not Path(source).exists())
    )
