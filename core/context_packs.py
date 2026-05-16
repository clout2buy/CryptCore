"""Budgeted context packs for each Crypt request."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools import REGISTRY

from . import entities, goals, knowledge_graph, memory_journal, prompt_injection_firewall, skills, work_threads


DEFAULT_BUDGET_TOKENS = 1_600
MIN_ITEM_TOKENS = 12


@dataclass(frozen=True)
class ContextItem:
    section: str
    kind: str
    title: str
    text: str
    source: str = ""
    priority: float = 0.5
    estimated_tokens: int = 0
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContextPack:
    query: str
    budget_tokens: int
    estimated_tokens: int
    omitted: int
    items: list[ContextItem] = field(default_factory=list)
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "budgetTokens": self.budget_tokens,
            "estimatedTokens": self.estimated_tokens,
            "omitted": self.omitted,
            "items": [asdict(item) for item in self.items],
            "text": self.text,
        }


def build(cwd: str | Path, text: str, *, budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> ContextPack:
    root = Path(cwd).expanduser().resolve()
    query = str(text or "").strip()
    budget = max(180, int(budget_tokens or DEFAULT_BUDGET_TOKENS))
    candidates = [_firewalled_item(root, item) for item in _candidate_items(root, query)]
    selected: list[ContextItem] = []
    used = _estimate_tokens("# Crypt Context Pack\n")
    for item in candidates:
        item_tokens = item.estimated_tokens or _estimate_tokens(_render_item_line(item))
        if item_tokens < MIN_ITEM_TOKENS:
            item_tokens = MIN_ITEM_TOKENS
        if used + item_tokens > budget:
            continue
        selected.append(ContextItem(**{**asdict(item), "estimated_tokens": item_tokens}))
        used += item_tokens
    rendered = render(selected)
    while selected and _estimate_tokens(rendered) > budget:
        selected.pop()
        rendered = render(selected)
    return ContextPack(
        query=query,
        budget_tokens=budget,
        estimated_tokens=_estimate_tokens(rendered),
        omitted=max(0, len(candidates) - len(selected)),
        items=selected,
        text=rendered,
    )


def render(items: list[ContextItem]) -> str:
    if not items:
        return ""
    grouped: dict[str, list[ContextItem]] = {}
    for item in items:
        grouped.setdefault(item.section, []).append(item)
    lines = ["# Crypt Context Pack"]
    for section, section_items in grouped.items():
        lines.append(f"## {section}")
        for item in section_items:
            lines.append(_render_item_line(item))
    return "\n".join(lines)


def prompt_section(cwd: str | Path, text: str, *, budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> str:
    return build(cwd, text, budget_tokens=budget_tokens).text


def preview(cwd: str | Path, text: str = "", *, budget_tokens: int = 600, limit: int = 8) -> dict[str, Any]:
    pack = build(cwd, text, budget_tokens=budget_tokens)
    data = pack.as_dict()
    data["items"] = data["items"][: max(1, limit)]
    data["text"] = pack.text[:2_000]
    return data


def _candidate_items(root: Path, query: str) -> list[ContextItem]:
    items: list[ContextItem] = []
    items.extend(_mission_items(root))
    items.extend(_graph_items(root, query))
    items.extend(_memory_items(root, query))
    items.extend(_entity_items(root, query))
    items.extend(_file_items(root, query))
    items.extend(_skill_items(root, query))
    items.extend(_tool_items(query))
    ranked = _rank(items, query)
    return _dedupe(ranked)


def _mission_items(root: Path) -> list[ContextItem]:
    items: list[ContextItem] = []
    for thread in work_threads.list_threads(root)[:8]:
        pending = next((task.get("title") for task in thread.tasks if task.get("status") != "done"), "")
        text = thread.next_action or pending or "Active thread."
        if thread.blockers:
            text += f" Blockers: {'; '.join(thread.blockers[:2])}."
        items.append(
            ContextItem(
                section="Mission State",
                kind="thread",
                title=thread.title,
                text=text,
                source=thread.thread_id,
                priority=0.94,
                tags=thread.tags,
            )
        )
    for goal in goals.list_goals(root)[:8]:
        text = goal.success_metric or goal.description or goal.status
        items.append(
            ContextItem(
                section="Mission State",
                kind="goal",
                title=goal.title,
                text=text,
                source=goal.goal_id,
                priority=0.88,
                tags=goal.tags,
            )
        )
    return items


def _graph_items(root: Path, query: str) -> list[ContextItem]:
    result = knowledge_graph.query(root, query, limit=10)
    out = []
    for node in result.nodes:
        out.append(
            ContextItem(
                section="Knowledge Graph",
                kind=node.kind,
                title=node.label,
                text=node.summary or node.ref,
                source=node.ref,
                priority=0.82,
                tags=node.tags,
            )
        )
    return out


def _memory_items(root: Path, query: str) -> list[ContextItem]:
    out = []
    query_tokens = _tokens(query)
    for item in memory_journal.filter_signals(root, include_sensitive=False)[:25]:
        text = str(item.get("text") or "")
        if not text:
            continue
        item_tokens = _tokens(text)
        relevant = not query_tokens or bool(query_tokens & item_tokens)
        priority = 0.76 if relevant else 0.45
        out.append(
            ContextItem(
                section="Memory",
                kind=str(item.get("memory_type") or item.get("category") or "memory"),
                title=str(item.get("category") or "memory"),
                text=text,
                source=str(item.get("signal_id") or ""),
                priority=priority,
                tags=[str(tag) for tag in item.get("tags", [])],
            )
        )
    return out


def _entity_items(root: Path, query: str) -> list[ContextItem]:
    query_tokens = _tokens(query)
    records = entities.list_entities(root, include_private=False, limit=80)
    if query_tokens:
        records = [
            record
            for record in records
            if query_tokens & _tokens(f"{record.name} {record.kind} {' '.join(record.tags)}")
        ]
    return [
        ContextItem(
            section="Entities",
            kind=record.kind,
            title=record.name,
            text=f"{record.summary if hasattr(record, 'summary') else record.kind}; mentions={record.mentions}",
            source=record.entity_id,
            priority=0.8,
            tags=record.tags,
        )
        for record in records
    ][:12]


def _file_items(root: Path, query: str) -> list[ContextItem]:
    out = []
    query_tokens = _tokens(query)
    try:
        entries = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:60]
    except OSError:
        return out
    for item in entries:
        if item.name.startswith(".") and item.name not in {".github", ".agents"}:
            continue
        tokens = _tokens(item.name)
        if query_tokens and not (query_tokens & tokens):
            continue
        out.append(
            ContextItem(
                section="Files",
                kind="folder" if item.is_dir() else "file",
                title=item.name,
                text=str(item),
                source="workspace",
                priority=0.62 if query_tokens else 0.38,
                tags=["folder" if item.is_dir() else "file"],
            )
        )
    return out[:12]


def _skill_items(root: Path, query: str) -> list[ContextItem]:
    out = []
    query_tokens = _tokens(query)
    for skill in skills.discover(root, include_disabled=True)[:30]:
        text = f"{skill.description or skill.title} {' '.join(skill.examples[:2])}"
        tokens = _tokens(f"{skill.name} {text}")
        if query_tokens and not (query_tokens & tokens):
            continue
        out.append(
            ContextItem(
                section="Skills",
                kind="skill",
                title=f"${skill.name}",
                text=text.strip() or str(skill.path),
                source=str(skill.path),
                priority=0.7 if skill.enabled else 0.3,
                tags=[skill.trust_level, "enabled" if skill.enabled else "blocked"],
            )
        )
    return out[:8]


def _tool_items(query: str) -> list[ContextItem]:
    out = []
    query_tokens = _tokens(query)
    for schema in REGISTRY.schemas()[:80]:
        name = str(schema.get("name") or "")
        desc = str(schema.get("description") or "")
        meta = schema.get("x_crypt") if isinstance(schema.get("x_crypt"), dict) else {}
        tokens = _tokens(f"{name} {desc} {meta.get('capability', '')}")
        if query_tokens and not (query_tokens & tokens):
            continue
        out.append(
            ContextItem(
                section="Tools",
                kind="tool",
                title=name,
                text=desc,
                source=str(meta.get("capability") or ""),
                priority=0.58,
                tags=[str(meta.get("risk") or "")],
            )
        )
    return out[:8]


def _rank(items: list[ContextItem], query: str) -> list[ContextItem]:
    query_tokens = _tokens(query)
    scored: list[tuple[float, ContextItem]] = []
    for item in items:
        overlap = len(query_tokens & _tokens(f"{item.title} {item.text} {' '.join(item.tags)}")) if query_tokens else 0
        score = item.priority + overlap * 0.18
        scored.append((score, item))
    scored.sort(key=lambda row: row[0], reverse=True)
    return [item for _, item in scored]


def _dedupe(items: list[ContextItem]) -> list[ContextItem]:
    seen: set[tuple[str, str, str]] = set()
    out: list[ContextItem] = []
    for item in items:
        key = (item.section.lower(), item.kind.lower(), item.title.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _firewalled_item(root: Path, item: ContextItem) -> ContextItem:
    scan = prompt_injection_firewall.scan_text(item.text, source=item.source or item.title)
    if scan.risk == "low":
        return item
    prompt_injection_firewall.record_scan(root, scan)
    tags = [*item.tags, "prompt-injection-risk", scan.risk]
    return ContextItem(**{**asdict(item), "text": scan.quoted_text, "tags": tags})


def _estimate_tokens(value: str) -> int:
    return max(1, int(len(str(value or "")) / 4) + 1)


def _render_item_line(item: ContextItem) -> str:
    source = f" ({item.source})" if item.source else ""
    return f"- [{item.kind}] {item.title}{source}: {item.text}"


def _tokens(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9][a-z0-9_.+-]{2,}", str(value or "").lower())}
