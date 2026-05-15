"""Durable local search index for workspace context."""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import artifact_studio, goals, learning, memory_journal, redact, session, settings, skills, work_threads


SCHEMA_VERSION = 1
MAX_DOCS = 220
MAX_TEXT_CHARS = 6_000
MAX_FILE_BYTES = 80_000
INDEX_MAX_AGE_SECONDS = 10 * 60
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{1,80}")


@dataclass(frozen=True)
class SearchDocument:
    doc_id: str
    source: str
    title: str
    text: str
    path: str = ""
    tags: list[str] = field(default_factory=list)
    updated_at: int = 0


@dataclass(frozen=True)
class SearchHit:
    doc_id: str
    source: str
    title: str
    score: float
    snippet: str
    path: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchIndex:
    root: str
    generated_at: int
    documents: list[SearchDocument] = field(default_factory=list)
    token_count: int = 0
    sources: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def index_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "local-search-index.json"


def load(cwd: str | Path, *, max_age_seconds: int = INDEX_MAX_AGE_SECONDS) -> SearchIndex | None:
    path = index_path(cwd)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return None
    index = _index_from_dict(data.get("index") or {})
    if index is None:
        return None
    if max_age_seconds >= 0 and time.time() - index.generated_at > max_age_seconds:
        return None
    return index


def refresh(cwd: str | Path) -> SearchIndex:
    root = Path(cwd).expanduser().resolve()
    docs = _collect(root)[:MAX_DOCS]
    sources: dict[str, int] = {}
    token_count = 0
    for doc in docs:
        sources[doc.source] = sources.get(doc.source, 0) + 1
        token_count += len(_tokens(f"{doc.title} {doc.text} {' '.join(doc.tags)}"))
    index = SearchIndex(root=str(root), generated_at=_now(), documents=docs, token_count=token_count, sources=sources)
    path = index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": SCHEMA_VERSION, "index": index.to_dict()}, indent=2), encoding="utf-8")
    settings.restrict_file_permissions(path)
    return index


def get(cwd: str | Path) -> SearchIndex:
    return load(cwd) or refresh(cwd)


def search(cwd: str | Path, query: str, *, limit: int = 8) -> list[SearchHit]:
    index = get(cwd)
    terms = _tokens(query)
    if not terms:
        docs = sorted(index.documents, key=lambda doc: doc.updated_at, reverse=True)[:limit]
        return [_hit(doc, score=0.1, terms=set()) for doc in docs]
    scored: list[SearchHit] = []
    idf = _idf(index.documents)
    for doc in index.documents:
        haystack = f"{doc.title} {doc.text} {' '.join(doc.tags)}"
        doc_tokens = _tokens(haystack)
        overlap = terms & doc_tokens
        if not overlap:
            continue
        score = sum(idf.get(term, 1.0) for term in overlap)
        if terms & _tokens(doc.title):
            score += 1.5
        if terms & set(tag.lower() for tag in doc.tags):
            score += 0.75
        scored.append(_hit(doc, score=round(score, 3), terms=terms))
    scored.sort(key=lambda hit: hit.score, reverse=True)
    return scored[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    index = get(cwd)
    return {
        "generatedAt": index.generated_at,
        "documents": len(index.documents),
        "tokenCount": index.token_count,
        "sources": dict(index.sources),
        "path": str(index_path(cwd)),
    }


def prompt_section(cwd: str | Path, text: str, *, limit: int = 5) -> str:
    hits = search(cwd, text, limit=limit)
    if not hits:
        return ""
    lines = ["# Local Search"]
    for hit in hits:
        location = f" ({hit.path})" if hit.path else ""
        lines.append(f"- {hit.source}: {hit.title}{location}; {hit.snippet}")
    return "\n".join(lines)


def _collect(root: Path) -> list[SearchDocument]:
    docs: list[SearchDocument] = []
    docs.extend(_workspace_docs(root))
    docs.extend(_memory_docs(root))
    docs.extend(_mission_docs(root))
    docs.extend(_artifact_docs(root))
    docs.extend(_skill_docs(root))
    return _dedupe_docs(docs)


def _workspace_docs(root: Path) -> list[SearchDocument]:
    candidates = []
    for pattern in ("README.md", "*.md", "docs/**/*.md", ".agents/skills/*/SKILL.md"):
        candidates.extend(root.glob(pattern))
    docs = []
    for path in sorted(set(candidates)):
        if not path.is_file() or _skip(path):
            continue
        text = _read_text(path)
        if not text:
            continue
        docs.append(
            SearchDocument(
                doc_id=_doc_id("doc", _rel(root, path)),
                source="doc",
                title=_title(text, path.stem),
                text=_trim(text),
                path=_rel(root, path),
                tags=["workspace", path.suffix.lower().lstrip(".")],
                updated_at=_mtime(path),
            )
        )
    return docs[:80]


def _memory_docs(root: Path) -> list[SearchDocument]:
    docs = []
    for item in memory_journal.filter_signals(root, include_sensitive=False)[:40]:
        text = str(item.get("text") or "")
        if not text:
            continue
        docs.append(
            SearchDocument(
                doc_id=_doc_id("memory", text),
                source="memory",
                title=str(item.get("category") or item.get("memory_type") or "memory"),
                text=_trim(text),
                tags=["memory", str(item.get("category") or "")],
                updated_at=int(item.get("updated_at") or 0),
            )
        )
    for lesson in learning.list_lessons(root)[:30]:
        docs.append(
            SearchDocument(
                doc_id=_doc_id("lesson", lesson.text),
                source="lesson",
                title="learned lesson",
                text=_trim(lesson.text),
                tags=["lesson", *lesson.tags],
                updated_at=int(lesson.created_at or 0),
            )
        )
    return docs


def _mission_docs(root: Path) -> list[SearchDocument]:
    docs = []
    for goal in goals.list_goals(root, include_all=True)[:40]:
        docs.append(
            SearchDocument(
                doc_id=goal.goal_id,
                source="mission",
                title=goal.title,
                text=_trim(" ".join([goal.description, goal.success_metric, goal.last_result])),
                tags=["goal", goal.status, *goal.tags],
                updated_at=goal.updated_at,
            )
        )
    for thread in work_threads.list_threads(root, include_all=True)[:40]:
        history_text = " ".join(str(item.get("note") or item.get("text") or "") for item in thread.history[-5:])
        task_text = " ".join(str(item.get("title") or item.get("description") or "") for item in thread.tasks[:10])
        docs.append(
            SearchDocument(
                doc_id=thread.thread_id,
                source="thread",
                title=thread.title,
                text=_trim(
                    " ".join(
                        [
                            thread.next_action,
                            " ".join(thread.blockers),
                            " ".join(thread.success_metrics),
                            task_text,
                            history_text,
                            " ".join(thread.artifacts),
                        ]
                    )
                ),
                tags=["thread", thread.state, *thread.tags],
                updated_at=thread.updated_at,
            )
        )
    return docs


def _artifact_docs(root: Path) -> list[SearchDocument]:
    docs = []
    for artifact in artifact_studio.list_artifacts(root, limit=60):
        docs.append(
            SearchDocument(
                doc_id=artifact.artifact_id,
                source="artifact",
                title=artifact.name,
                text=_trim(" ".join([artifact.preview, artifact.provenance, " ".join(artifact.notes)])),
                path=artifact.rel_path,
                tags=["artifact", artifact.kind, artifact.status],
                updated_at=artifact.updated_at,
            )
        )
    return docs


def _skill_docs(root: Path) -> list[SearchDocument]:
    docs = []
    for skill in skills.discover(root, include_disabled=True)[:60]:
        docs.append(
            SearchDocument(
                doc_id=_doc_id("skill", skill.name),
                source="skill",
                title=skill.name,
                text=_trim(" ".join([skill.title, skill.description, " ".join(skill.examples)])),
                path=str(skill.path),
                tags=["skill", skill.trust_level, "enabled" if skill.enabled else "disabled"],
                updated_at=_mtime(skill.path),
            )
        )
    return docs


def _index_from_dict(data: dict[str, Any]) -> SearchIndex | None:
    try:
        documents = [
            SearchDocument(
                doc_id=str(item.get("doc_id") or ""),
                source=str(item.get("source") or ""),
                title=str(item.get("title") or ""),
                text=str(item.get("text") or ""),
                path=str(item.get("path") or ""),
                tags=[str(tag) for tag in item.get("tags", []) if str(tag).strip()],
                updated_at=int(item.get("updated_at") or 0),
            )
            for item in data.get("documents", [])
            if isinstance(item, dict)
        ]
        return SearchIndex(
            root=str(data.get("root") or ""),
            generated_at=int(data.get("generated_at") or 0),
            documents=[doc for doc in documents if doc.doc_id and doc.source and doc.title],
            token_count=int(data.get("token_count") or 0),
            sources={str(k): int(v) for k, v in dict(data.get("sources") or {}).items()},
        )
    except Exception:
        return None


def _hit(doc: SearchDocument, *, score: float, terms: set[str]) -> SearchHit:
    return SearchHit(
        doc_id=doc.doc_id,
        source=doc.source,
        title=doc.title,
        score=score,
        snippet=_snippet(doc.text, terms),
        path=doc.path,
        tags=doc.tags,
    )


def _idf(docs: list[SearchDocument]) -> dict[str, float]:
    counts: dict[str, int] = {}
    for doc in docs:
        for token in _tokens(f"{doc.title} {doc.text} {' '.join(doc.tags)}"):
            counts[token] = counts.get(token, 0) + 1
    total = max(1, len(docs))
    return {token: 1.0 + math.log(total / max(1, count)) for token, count in counts.items()}


def _tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(str(text or ""))}


def _snippet(text: str, terms: set[str]) -> str:
    clean = " ".join(str(text or "").split())
    if not clean:
        return "No preview available."
    lower = clean.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    start = max(0, min(positions) - 80) if positions else 0
    snippet = clean[start : start + 260].strip()
    if start:
        snippet = "..." + snippet
    if start + 260 < len(clean):
        snippet += "..."
    return snippet


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean.startswith("#"):
            return clean.lstrip("#").strip()[:160] or fallback
    return fallback[:160] or "document"


def _read_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > MAX_FILE_BYTES:
        data = data[:MAX_FILE_BYTES]
    if b"\x00" in data:
        return ""
    return redact.text(data.decode("utf-8", errors="replace"))


def _trim(text: str) -> str:
    clean = " ".join(redact.text(str(text or "")).split())
    return clean[:MAX_TEXT_CHARS]


def _doc_id(prefix: str, value: str) -> str:
    import hashlib

    return f"{prefix}_" + hashlib.sha1(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def _dedupe_docs(docs: list[SearchDocument]) -> list[SearchDocument]:
    out: list[SearchDocument] = []
    seen: set[str] = set()
    for doc in docs:
        key = doc.doc_id.lower()
        if key in seen or not doc.text.strip():
            continue
        seen.add(key)
        out.append(doc)
    return out


def _skip(path: Path) -> bool:
    return any(part in {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"} for part in path.parts)


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _mtime(path: Path) -> int:
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


def _now() -> int:
    return int(time.time())
