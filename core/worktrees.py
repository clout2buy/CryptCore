"""Optional git worktree isolation primitives for agent workers."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import settings


@dataclass(frozen=True)
class WorktreeSpec:
    branch: str
    path: Path
    base: str = "HEAD"


def supported(cwd: str | Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        return False


def is_dirty(cwd: str | Path) -> bool:
    r = subprocess.run(
        ["git", "-C", str(cwd), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"git status failed: {detail}")
    return bool(r.stdout.strip())


def create(cwd: str | Path, spec: WorktreeSpec) -> Path:
    if not supported(cwd):
        raise RuntimeError("worktree isolation requires a git repository")
    spec.path.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["git", "-C", str(cwd), "worktree", "add", "-b", spec.branch, str(spec.path), spec.base],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"git worktree add failed: {detail}")
    return spec.path


def diff(cwd: str | Path) -> str:
    r = subprocess.run(
        ["git", "-C", str(cwd), "diff", "--no-color"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"git diff failed: {detail}")
    return r.stdout


def changed_files(cwd: str | Path) -> list[str]:
    tracked = subprocess.run(
        ["git", "-C", str(cwd), "diff", "--name-only", "--no-color"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if tracked.returncode != 0:
        detail = (tracked.stderr or tracked.stdout or "").strip()
        raise RuntimeError(f"git diff --name-only failed: {detail}")
    status = subprocess.run(
        ["git", "-C", str(cwd), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if status.returncode != 0:
        detail = (status.stderr or status.stdout or "").strip()
        raise RuntimeError(f"git status failed: {detail}")
    files = {line.strip() for line in tracked.stdout.splitlines() if line.strip()}
    for line in status.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            files.add(path)
    return sorted(files)


def untracked_files(cwd: str | Path) -> list[str]:
    status = subprocess.run(
        ["git", "-C", str(cwd), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if status.returncode != 0:
        detail = (status.stderr or status.stdout or "").strip()
        raise RuntimeError(f"git status failed: {detail}")
    out: list[str] = []
    for line in status.stdout.splitlines():
        if line.startswith("?? ") and len(line) > 3:
            out.append(line[3:].strip())
    return sorted(out)


def remove(main_cwd: str | Path, path: str | Path, *, force: bool = False) -> str:
    target = _managed_worktree_path(path)
    if not target.exists():
        _prune(main_cwd)
        return f"worktree already removed: {target}"
    cmd = ["git", "-C", str(main_cwd), "worktree", "remove"]
    if force:
        cmd.append("--force")
    cmd.append(str(target))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"git worktree remove failed: {detail}")
    _prune(main_cwd)
    return f"removed worktree: {target}"


def _managed_worktree_path(path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    root = (settings.APP_DIR / "worktrees").expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"refusing to remove unmanaged worktree path: {target}") from exc
    return target


def _prune(cwd: str | Path) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), "worktree", "prune"],
        capture_output=True,
        text=True,
        timeout=30,
    )
