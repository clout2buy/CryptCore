"""Project intelligence cache for Crypt workspaces."""
from __future__ import annotations

import json
import subprocess
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import memory, session, skills


PROFILE_SCHEMA_VERSION = 2
PROFILE_MAX_AGE_SECONDS = 15 * 60


@dataclass(frozen=True)
class ProjectProfile:
    root: str
    generated_at: int
    languages: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    ci_files: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    build_commands: list[str] = field(default_factory=list)
    instruction_files: list[str] = field(default_factory=list)
    skill_count: int = 0
    git_branch: str = ""
    git_dirty_count: int = 0
    key_files: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)


def profile_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "project-profile.json"


def load(cwd: str | Path, *, max_age_seconds: int = PROFILE_MAX_AGE_SECONDS) -> ProjectProfile | None:
    path = profile_path(cwd)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("schema") != PROFILE_SCHEMA_VERSION:
        return None
    profile = _profile_from_dict(data.get("profile") or {})
    if profile is None:
        return None
    if max_age_seconds >= 0 and time.time() - profile.generated_at > max_age_seconds:
        return None
    return profile


def scan(cwd: str | Path) -> ProjectProfile:
    root = Path(cwd).expanduser().resolve()
    key_files = _key_files(root)
    package_managers = _package_managers(root)
    languages = _languages(root, key_files)
    package = _package_json(root)
    pyproject = _pyproject(root)
    requirements = _requirements(root)
    test_commands = _test_commands(root, package)
    build_commands = _build_commands(root, package)
    frameworks = _frameworks(root, package, pyproject, requirements)
    entrypoints = _entrypoints(root, package, pyproject)
    ci_files = _ci_files(root)
    instruction_files = [
        _rel(root, path)
        for path in memory.project_instruction_files(root)
    ]
    branch, dirty = _git_state(root)
    return ProjectProfile(
        root=str(root),
        generated_at=int(time.time()),
        languages=languages,
        package_managers=package_managers,
        frameworks=frameworks,
        entrypoints=entrypoints,
        ci_files=ci_files,
        test_commands=test_commands,
        build_commands=build_commands,
        instruction_files=instruction_files,
        skill_count=len(skills.discover(root)),
        git_branch=branch,
        git_dirty_count=dirty,
        key_files=key_files,
        risk_flags=_risk_flags(
            test_commands=test_commands,
            ci_files=ci_files,
            key_files=key_files,
            git_dirty_count=dirty,
        ),
    )


def refresh(cwd: str | Path) -> ProjectProfile:
    profile = scan(cwd)
    path = profile_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": PROFILE_SCHEMA_VERSION,
                "profile": asdict(profile),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    session.settings.restrict_file_permissions(path)
    return profile


def get(cwd: str | Path) -> ProjectProfile:
    return load(cwd) or refresh(cwd)


def prompt_section(cwd: str | Path) -> str:
    profile = get(cwd)
    parts = ["# Project Intelligence"]
    if profile.languages:
        parts.append("- Languages: " + ", ".join(profile.languages))
    if profile.package_managers:
        parts.append("- Package managers: " + ", ".join(profile.package_managers))
    if profile.frameworks:
        parts.append("- Frameworks/libraries: " + ", ".join(profile.frameworks[:10]))
    if profile.entrypoints:
        parts.append("- Entry points: " + "; ".join(profile.entrypoints[:8]))
    if profile.ci_files:
        parts.append("- CI files: " + ", ".join(profile.ci_files[:6]))
    if profile.test_commands:
        parts.append("- Likely test commands: " + "; ".join(profile.test_commands[:6]))
    if profile.build_commands:
        parts.append("- Likely build commands: " + "; ".join(profile.build_commands[:4]))
    if profile.instruction_files:
        parts.append("- Instruction files: " + ", ".join(profile.instruction_files[:6]))
    if profile.skill_count:
        parts.append(f"- Visible skills: {profile.skill_count}")
    if profile.git_branch:
        parts.append(f"- Git: {profile.git_branch}, {profile.git_dirty_count} changed file(s)")
    if profile.key_files:
        parts.append("- Key files: " + ", ".join(profile.key_files[:12]))
    if profile.risk_flags:
        parts.append("- Attention flags: " + "; ".join(profile.risk_flags[:6]))
    return "\n".join(parts)


def format_profile(cwd: str | Path, *, refresh_first: bool = False) -> str:
    profile = refresh(cwd) if refresh_first else get(cwd)
    rows = {
        "root": profile.root,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(profile.generated_at)),
        "languages": ", ".join(profile.languages) or "(none)",
        "package_managers": ", ".join(profile.package_managers) or "(none)",
        "frameworks": ", ".join(profile.frameworks) or "(none)",
        "entrypoints": "\n".join(profile.entrypoints) or "(none detected)",
        "ci_files": ", ".join(profile.ci_files) or "(none detected)",
        "test_commands": "\n".join(profile.test_commands) or "(none detected)",
        "build_commands": "\n".join(profile.build_commands) or "(none detected)",
        "instruction_files": ", ".join(profile.instruction_files) or "(none)",
        "skills": str(profile.skill_count),
        "git": f"{profile.git_branch or '(none)'}; {profile.git_dirty_count} changed file(s)",
        "key_files": ", ".join(profile.key_files) or "(none)",
        "attention": "\n".join(profile.risk_flags) or "(none)",
    }
    return "\n".join(f"{key}: {value}" for key, value in rows.items())


def _profile_from_dict(data: dict[str, Any]) -> ProjectProfile | None:
    try:
        return ProjectProfile(
            root=str(data.get("root") or ""),
            generated_at=int(data.get("generated_at") or 0),
            languages=[str(item) for item in data.get("languages", [])],
            package_managers=[str(item) for item in data.get("package_managers", [])],
            frameworks=[str(item) for item in data.get("frameworks", [])],
            entrypoints=[str(item) for item in data.get("entrypoints", [])],
            ci_files=[str(item) for item in data.get("ci_files", [])],
            test_commands=[str(item) for item in data.get("test_commands", [])],
            build_commands=[str(item) for item in data.get("build_commands", [])],
            instruction_files=[str(item) for item in data.get("instruction_files", [])],
            skill_count=int(data.get("skill_count") or 0),
            git_branch=str(data.get("git_branch") or ""),
            git_dirty_count=int(data.get("git_dirty_count") or 0),
            key_files=[str(item) for item in data.get("key_files", [])],
            risk_flags=[str(item) for item in data.get("risk_flags", [])],
        )
    except Exception:
        return None


def _key_files(root: Path) -> list[str]:
    names = (
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "pnpm-lock.yaml",
        "package-lock.json",
        "yarn.lock",
        "Cargo.toml",
        "go.mod",
        "Makefile",
        "justfile",
        "README.md",
    )
    return [name for name in names if (root / name).exists()]


def _package_managers(root: Path) -> list[str]:
    out: list[str] = []
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        out.append("python")
    if (root / "uv.lock").exists():
        out.append("uv")
    if (root / "package.json").exists():
        if (root / "pnpm-lock.yaml").exists():
            out.append("pnpm")
        elif (root / "yarn.lock").exists():
            out.append("yarn")
        else:
            out.append("npm")
    if (root / "Cargo.toml").exists():
        out.append("cargo")
    if (root / "go.mod").exists():
        out.append("go")
    return out


def _languages(root: Path, key_files: list[str]) -> list[str]:
    langs: set[str] = set()
    if any(name in key_files for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt")):
        langs.add("Python")
    if "package.json" in key_files:
        langs.add("JavaScript/TypeScript")
    if "Cargo.toml" in key_files:
        langs.add("Rust")
    if "go.mod" in key_files:
        langs.add("Go")
    suffix_map = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".rs": "Rust",
        ".go": "Go",
    }
    counts: dict[str, int] = {}
    scanned = 0
    try:
        for path in root.rglob("*"):
            if not path.is_file() or _skip(path):
                continue
            scanned += 1
            if scanned > 5000:
                break
            lang = suffix_map.get(path.suffix.lower())
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
    except OSError:
        pass
    langs.update(lang for lang, count in counts.items() if count >= 2)
    return sorted(langs)


def _package_json(root: Path) -> dict[str, Any]:
    path = root / "package.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    if not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _requirements(root: Path) -> list[str]:
    names: list[str] = []
    for path in (root / "requirements.txt", root / "requirements-dev.txt"):
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            name = _dependency_name(line)
            if name:
                names.append(name)
    return _dedupe(names)


def _frameworks(
    root: Path,
    package: dict[str, Any],
    pyproject: dict[str, Any],
    requirements: list[str],
) -> list[str]:
    deps = _dependency_names(package, pyproject, requirements)
    detected: list[str] = []
    signals = {
        "Python package": bool(pyproject),
        "Node package": bool(package),
        "Pytest": "pytest" in deps or (root / "pytest.ini").exists(),
        "Ruff": "ruff" in deps,
        "Rich TUI": "rich" in deps,
        "FastAPI": "fastapi" in deps,
        "Django": "django" in deps,
        "Flask": "flask" in deps,
        "Typer": "typer" in deps,
        "Pydantic": "pydantic" in deps,
        "Anthropic SDK": "anthropic" in deps,
        "OpenAI SDK": "openai" in deps,
        "Google Auth": "google-auth" in deps or "google-auth-oauthlib" in deps,
        "React": "react" in deps,
        "Next.js": "next" in deps,
        "Vite": "vite" in deps,
        "Vue": "vue" in deps,
        "Svelte": "svelte" in deps,
        "Tailwind": "tailwindcss" in deps,
        "TypeScript": "typescript" in deps,
        "Vitest": "vitest" in deps,
        "Playwright": "playwright" in deps or "@playwright/test" in deps,
        "Electron": "electron" in deps,
    }
    for label, present in signals.items():
        if present:
            detected.append(label)
    return detected


def _dependency_names(
    package: dict[str, Any],
    pyproject: dict[str, Any],
    requirements: list[str],
) -> set[str]:
    names = set(requirements)
    for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        values = package.get(key)
        if isinstance(values, dict):
            names.update(str(name).strip().lower() for name in values if str(name).strip())
    project = pyproject.get("project") if isinstance(pyproject, dict) else {}
    if isinstance(project, dict):
        for item in project.get("dependencies") or []:
            name = _dependency_name(str(item))
            if name:
                names.add(name)
        optional = project.get("optional-dependencies") or {}
        if isinstance(optional, dict):
            for group in optional.values():
                if not isinstance(group, list):
                    continue
                for item in group:
                    name = _dependency_name(str(item))
                    if name:
                        names.add(name)
    tool = pyproject.get("tool") if isinstance(pyproject, dict) else {}
    poetry = tool.get("poetry") if isinstance(tool, dict) else {}
    if isinstance(poetry, dict):
        for key in ("dependencies", "dev-dependencies"):
            values = poetry.get(key)
            if isinstance(values, dict):
                names.update(str(name).strip().lower() for name in values if str(name).strip().lower() != "python")
    uv = tool.get("uv") if isinstance(tool, dict) else {}
    if isinstance(uv, dict):
        for item in uv.get("dev-dependencies") or []:
            name = _dependency_name(str(item))
            if name:
                names.add(name)
    return {name for name in names if name}


def _dependency_name(spec: str) -> str:
    spec = spec.strip()
    if not spec or spec.startswith("#") or spec.startswith(("-r ", "--")):
        return ""
    spec = spec.split("#", 1)[0].strip()
    if not spec:
        return ""
    if spec.startswith((".", "/", "git+", "http://", "https://")):
        return ""
    name = []
    for char in spec:
        if char.isalnum() or char in "-_.":
            name.append(char)
            continue
        break
    return "".join(name).replace("_", "-").lower()


def _entrypoints(root: Path, package: dict[str, Any], pyproject: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if (root / "main.py").exists():
        out.append("python main.py")
    for path in sorted(root.glob("*/__main__.py")):
        if (path.parent / "__init__.py").exists():
            out.append(f"python -m {path.parent.name}")
    project = pyproject.get("project") if isinstance(pyproject, dict) else {}
    scripts = project.get("scripts") if isinstance(project, dict) else {}
    if isinstance(scripts, dict):
        for name, target in sorted(scripts.items()):
            out.append(f"{name} -> {target}")
    package_scripts = package.get("scripts")
    if isinstance(package_scripts, dict):
        for name in sorted(package_scripts):
            out.append(f"npm run {name}")
    if (root / "Makefile").exists():
        out.append("make")
    if (root / "Dockerfile").exists():
        out.append("docker build .")
    if (root / "docker-compose.yml").exists() or (root / "compose.yml").exists():
        out.append("docker compose up")
    return _dedupe(out)


def _ci_files(root: Path) -> list[str]:
    out: list[str] = []
    workflows = root / ".github" / "workflows"
    if workflows.exists():
        for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
            out.append(_rel(root, path))
    for name in (".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", "circle.yml"):
        path = root / name
        if path.exists():
            out.append(name)
    return _dedupe(out)


def _risk_flags(
    *,
    test_commands: list[str],
    ci_files: list[str],
    key_files: list[str],
    git_dirty_count: int,
) -> list[str]:
    out: list[str] = []
    if not test_commands:
        out.append("no automated test command detected")
    if not ci_files:
        out.append("no CI workflow detected")
    if "README.md" not in key_files:
        out.append("missing README.md")
    if git_dirty_count:
        out.append(f"git tree has {git_dirty_count} changed file(s)")
    return out


def _test_commands(root: Path, package: dict[str, Any]) -> list[str]:
    out: list[str] = []
    scripts = package.get("scripts") if isinstance(package, dict) else {}
    if isinstance(scripts, dict):
        for name in ("test", "test:unit", "lint", "typecheck"):
            if name in scripts:
                runner = "pnpm" if (root / "pnpm-lock.yaml").exists() else "npm"
                out.append(f"{runner} run {name}")
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists() or (root / "tests").exists():
        out.append("python -m pytest")
    if (root / "pyproject.toml").exists():
        out.append("python -m ruff check .")
    if (root / "Cargo.toml").exists():
        out.append("cargo test")
    if (root / "go.mod").exists():
        out.append("go test ./...")
    return _dedupe(out)


def _build_commands(root: Path, package: dict[str, Any]) -> list[str]:
    out: list[str] = []
    scripts = package.get("scripts") if isinstance(package, dict) else {}
    if isinstance(scripts, dict):
        for name in ("build", "compile"):
            if name in scripts:
                runner = "pnpm" if (root / "pnpm-lock.yaml").exists() else "npm"
                out.append(f"{runner} run {name}")
    if (root / "pyproject.toml").exists():
        out.append("python -m build")
    if (root / "Cargo.toml").exists():
        out.append("cargo build")
    if (root / "go.mod").exists():
        out.append("go build ./...")
    return _dedupe(out)


def _git_state(root: Path) -> tuple[str, int]:
    try:
        branch = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--short"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return "", 0
    branch_text = (branch.stdout or "").strip()
    dirty = len([line for line in (status.stdout or "").splitlines() if line.strip()])
    return branch_text, dirty


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _skip(path: Path) -> bool:
    return any(part in {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"} for part in path.parts)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
