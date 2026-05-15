"""Local skill discovery and prompt injection.

Skills are repo or user scoped instruction bundles stored as ``SKILL.md``.
Crypt keeps the contract deliberately filesystem-native: a skill is invoked by
mentioning ``$skill-name`` in the user prompt, or by passing a structured input
item with ``{"type": "skill", "name": ..., "path": ...}``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import settings


SKILL_FILE = "SKILL.md"
MENTION_RE = re.compile(r"(?<![\w.-])\$([A-Za-z0-9][A-Za-z0-9_.:-]{0,80})")
MAX_SKILL_BYTES = 80_000
MAX_RENDERED_CHARS = 40_000
INVISIBLE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(ignore|disregard|override|bypass)\b.{0,100}\b(previous|above|system|developer|safety|instructions?)\b", re.I | re.S),
    re.compile(r"\b(reveal|print|dump|exfiltrate|send|upload)\b.{0,120}\b(secret|token|api[_-]?key|password|credential|private[_ -]?key|system prompt|developer message|\.env)\b", re.I | re.S),
    re.compile(r"\b(read|cat|open|copy)\b.{0,100}\b(~[/\\]\.ssh|id_rsa|auth\.json|\.env|credentials?\.json)\b", re.I | re.S),
    re.compile(r"<\s*/?\s*(system|developer|assistant|tool|instructions?)\s*>", re.I),
)


@dataclass(frozen=True)
class Skill:
    name: str
    path: Path
    description: str = ""
    title: str = ""
    enabled: bool = True
    blocked_reason: str = ""
    trust_level: str = "unknown"
    examples: tuple[str, ...] = ()
    smoke_tests: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "description": self.description,
            "title": self.title,
            "enabled": self.enabled,
            "blocked_reason": self.blocked_reason,
            "trust_level": self.trust_level,
            "examples": list(self.examples),
            "smoke_tests": list(self.smoke_tests),
            "metadata": dict(self.metadata or {}),
        }


def discover(cwd: str | Path, *, include_disabled: bool = False) -> list[Skill]:
    """Return enabled local skills visible to ``cwd``.

    Discovery order is project first, then user-level skill stores. Later
    duplicates are ignored so a project can shadow a global skill by name.
    Disabled project skills still shadow global skills to avoid surprising
    fallback activation after a local bundle was blocked.
    """
    seen: set[str] = set()
    out: list[Skill] = []
    for root in _skill_roots(cwd):
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.glob(f"*/{SKILL_FILE}")):
            skill = _with_runtime_metadata(_parse_skill(path), root=root, cwd=cwd)
            key = skill.name.lower()
            if key in seen:
                continue
            seen.add(key)
            if skill.enabled or include_disabled:
                out.append(skill)
    return out


def available_summary(cwd: str | Path, *, limit: int = 12_000) -> str:
    skills = discover(cwd)
    if not skills:
        return ""
    lines = []
    used = 0
    for skill in skills:
        desc = f" - {skill.description}" if skill.description else ""
        line = f"- ${skill.name}{desc}"
        if used + len(line) + 1 > limit:
            lines.append("- ... [skill list truncated]")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def render_for_messages(messages: list[dict], cwd: str | Path) -> str:
    """Render invoked skill instructions for the latest user input."""
    latest = _latest_user_content(messages)
    if latest is None:
        return ""

    requested = _requested_skills(latest)
    if not requested:
        return ""

    available = {skill.name.lower(): skill for skill in discover(cwd)}
    selected: list[Skill] = []
    for item in requested:
        if isinstance(item, Path):
            if not item.exists() or not _path_is_allowed_skill(item, cwd):
                continue
            skill = _parse_skill(item)
        else:
            skill = available.get(item.lower())
            if skill is None:
                continue
        if not skill.enabled:
            continue
        if skill.name.lower() not in {s.name.lower() for s in selected}:
            selected.append(skill)

    chunks: list[str] = []
    used = 0
    for skill in selected:
        body = _read_skill(skill.path)
        header = f"## ${skill.name}\nPath: {skill.path}\n"
        chunk = header + body.strip()
        remaining = MAX_RENDERED_CHARS - used
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunk = chunk[:remaining].rstrip() + "\n... [skill truncated]"
        chunks.append(chunk)
        used += len(chunk)

    if not chunks:
        return ""
    return (
        "# Active Skill Instructions\n"
        "The user invoked these local skills for this turn. Follow them as higher-priority "
        "workflow guidance unless they conflict with system/developer safety rules.\n\n"
        + "\n\n".join(chunks)
    )


def _skill_roots(cwd: str | Path) -> list[Path]:
    workspace = Path(cwd).expanduser().resolve()
    home = Path.home()
    return [
        workspace / ".crypt" / "skills",
        workspace / ".agents" / "skills",
        settings.APP_DIR / "skills",
        home / ".agents" / "skills",
        home / ".codex" / "skills",
        home / ".config" / "agents" / "skills",
    ]


def _parse_skill(path: Path) -> Skill:
    name = path.parent.name
    title = ""
    description = ""
    examples: tuple[str, ...] = ()
    smoke_tests: tuple[str, ...] = ()
    text = _read_skill(path)
    blocked_reason = _blocked_reason(text)
    frontmatter, body = _split_frontmatter(text)
    if frontmatter:
        for key, value in frontmatter.items():
            if key == "name" and value:
                name = _safe_name(value)
            elif key == "description":
                description = value
            elif key in {"title", "display_name"}:
                title = value
            elif key in {"example", "examples"}:
                examples = tuple(_split_list(value))
            elif key in {"smoke_test", "smoke_tests"}:
                smoke_tests = tuple(_split_list(value))
    if not title:
        title = _first_heading(body)
    if not description:
        description = _first_paragraph(body)
    if not examples:
        examples = tuple(_section_bullets(body, "examples"))
    if not smoke_tests:
        smoke_tests = tuple(_section_bullets(body, "smoke tests"))
    return Skill(
        name=_safe_name(name),
        path=path.resolve(),
        description=description[:500],
        title=title[:160],
        enabled=not blocked_reason,
        blocked_reason=blocked_reason,
        examples=examples[:6],
        smoke_tests=smoke_tests[:6],
    )


def _with_runtime_metadata(skill: Skill, *, root: Path, cwd: str | Path) -> Skill:
    workspace = Path(cwd).expanduser().resolve()
    resolved_root = root.resolve()
    trust = "unknown"
    try:
        resolved_root.relative_to(workspace)
        trust = "project"
    except ValueError:
        try:
            resolved_root.relative_to(settings.APP_DIR.resolve())
            trust = "app"
        except ValueError:
            try:
                resolved_root.relative_to(Path.home().resolve())
                trust = "user"
            except ValueError:
                trust = "unknown"
    if not skill.enabled:
        trust = "blocked"
    return Skill(
        name=skill.name,
        path=skill.path,
        description=skill.description,
        title=skill.title,
        enabled=skill.enabled,
        blocked_reason=skill.blocked_reason,
        trust_level=trust,
        examples=skill.examples,
        smoke_tests=skill.smoke_tests,
        metadata={"root": str(resolved_root), "source": trust},
    )


def _read_skill(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > MAX_SKILL_BYTES:
        data = data[:MAX_SKILL_BYTES]
    return data.decode("utf-8", errors="replace")


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for idx, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = idx
            break
    if end is None:
        return {}, text
    data: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower().replace("-", "_")
        value = value.strip().strip('"').strip("'")
        if key and value:
            data[key] = value
    return data, "\n".join(lines[end + 1 :])


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def _first_paragraph(text: str) -> str:
    paragraph: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped or stripped.startswith("#"):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
        if len(" ".join(paragraph)) > 500:
            break
    return " ".join(paragraph)


def _section_bullets(text: str, heading: str) -> list[str]:
    heading_key = heading.strip().lower()
    lines = text.replace("\r\n", "\n").split("\n")
    in_section = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            current = stripped.lstrip("#").strip().lower()
            if in_section and current != heading_key:
                break
            in_section = current == heading_key
            continue
        if not in_section:
            continue
        if stripped.startswith(("-", "*")):
            item = stripped[1:].strip()
            if item:
                out.append(item[:240])
    return out


def _split_list(value: str) -> list[str]:
    return [item.strip()[:240] for item in re.split(r"\s*[|,]\s*", value) if item.strip()]


def _safe_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(name).strip()).strip("-")
    return clean or "skill"


def _latest_user_content(messages: list[dict]) -> Any:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return message.get("content")
    return None


def _requested_skills(content: Any) -> list[str | Path]:
    requested: list[str | Path] = []
    texts: list[str] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            typ = item.get("type")
            if typ == "text":
                texts.append(str(item.get("text") or ""))
            elif typ == "skill":
                path = str(item.get("path") or "").strip()
                if path:
                    requested.append(Path(path).expanduser())
                elif item.get("name"):
                    requested.append(_safe_name(str(item["name"])))
    for text in texts:
        requested.extend(
            _safe_name(match.group(1))
            for match in MENTION_RE.finditer(text)
            if not _looks_like_env_var(match.group(1))
        )
    return requested


def _looks_like_env_var(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", value or ""))


def _path_is_allowed_skill(path: Path, cwd: str | Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    if resolved.name != SKILL_FILE:
        return False
    for root in _skill_roots(cwd):
        try:
            resolved.relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


def _blocked_reason(text: str) -> str:
    if INVISIBLE_CONTROL_RE.search(text):
        return "contains invisible control characters"
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            return "contains prompt-injection or secret-exfiltration language"
    return ""
