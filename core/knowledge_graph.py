"""Workspace knowledge graph for retrieval across Crypt runtime state."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools import REGISTRY

from . import artifact_studio, entities, goals, memory_journal, skills, work_threads


MAX_GRAPH_NODES = 180
MAX_GRAPH_EDGES = 420
STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "about",
    "what",
    "when",
    "where",
    "your",
    "crypt",
    "user",
    "need",
    "want",
}


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: str
    label: str
    summary: str = ""
    ref: str = ""
    tags: list[str] = field(default_factory=list)
    updated_at: int = 0


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    weight: float = 1.0


@dataclass(frozen=True)
class GraphSnapshot:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


@dataclass(frozen=True)
class GraphQueryResult:
    query: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def build_graph(cwd: str | Path, *, max_nodes: int = MAX_GRAPH_NODES) -> GraphSnapshot:
    """Build a compact graph from the current workspace state."""
    root = Path(cwd).expanduser().resolve()
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    goal_nodes = _goal_nodes(root)
    thread_nodes, thread_edges = _thread_nodes(root)
    nodes.extend(goal_nodes)
    nodes.extend(thread_nodes)
    edges.extend(thread_edges)
    nodes.extend(_memory_nodes(root))
    nodes.extend(_entity_nodes(root))
    artifact_nodes, artifact_edges = _artifact_nodes(root)
    nodes.extend(artifact_nodes)
    edges.extend(artifact_edges)
    nodes.extend(_skill_nodes(root))
    nodes.extend(_tool_nodes())
    nodes.extend(_file_nodes(root))

    unique_nodes = _unique_nodes(nodes)[: max(1, max_nodes)]
    edges.extend(_overlap_edges(unique_nodes))
    unique_edges = _unique_edges(edges, {node.node_id for node in unique_nodes})
    return GraphSnapshot(nodes=unique_nodes, edges=unique_edges[:MAX_GRAPH_EDGES])


def query(cwd: str | Path, text: str, *, limit: int = 10) -> GraphQueryResult:
    graph = build_graph(cwd)
    query_tokens = _tokens(text)
    if not query_tokens:
        selected = graph.nodes[: max(1, limit)]
    else:
        scored: list[tuple[float, GraphNode]] = []
        edge_counts = _edge_counts(graph.edges)
        for node in graph.nodes:
            node_tokens = _node_tokens(node)
            overlap = query_tokens & node_tokens
            if not overlap:
                continue
            score = len(overlap) * 2.0
            score += min(2.0, edge_counts.get(node.node_id, 0) * 0.2)
            if node.kind in {"goal", "thread", "entity", "artifact"}:
                score += 0.5
            scored.append((score, node))
        scored.sort(key=lambda row: (row[0], row[1].updated_at), reverse=True)
        selected = [node for _, node in scored[: max(1, limit)]]
    selected_ids = {node.node_id for node in selected}
    selected_edges = [
        edge
        for edge in graph.edges
        if edge.source in selected_ids and edge.target in selected_ids
    ][: max(0, limit * 2)]
    return GraphQueryResult(query=str(text or ""), nodes=selected, edges=selected_edges)


def prompt_section(cwd: str | Path, *, text: str = "", limit: int = 8) -> str:
    result = query(cwd, text, limit=limit) if text else GraphQueryResult("", build_graph(cwd).nodes[:limit], [])
    if not result.nodes:
        return ""
    lines = ["# Knowledge Graph Context"]
    for node in result.nodes[:limit]:
        summary = f" - {node.summary}" if node.summary else ""
        lines.append(f"- [{node.kind}] {node.label}{summary}")
    if result.edges:
        lines.append("## Links")
        for edge in result.edges[: max(2, limit // 2)]:
            lines.append(f"- {edge.source} {edge.relation} {edge.target}")
    return "\n".join(lines)


def snapshot(cwd: str | Path, *, preview: int = 12) -> dict[str, Any]:
    graph = build_graph(cwd)
    counts: dict[str, int] = {}
    for node in graph.nodes:
        counts[node.kind] = counts.get(node.kind, 0) + 1
    return {
        "nodeCount": len(graph.nodes),
        "edgeCount": len(graph.edges),
        "kindCounts": counts,
        "nodes": [asdict(node) for node in graph.nodes[: max(1, preview)]],
        "edges": [asdict(edge) for edge in graph.edges[: max(1, preview)]],
    }


def _goal_nodes(root: Path) -> list[GraphNode]:
    out = []
    for goal in goals.list_goals(root, include_all=True)[:40]:
        out.append(
            GraphNode(
                node_id=f"goal:{goal.goal_id}",
                kind="goal",
                label=goal.title,
                summary=goal.success_metric or goal.description,
                ref=goal.goal_id,
                tags=["mission", goal.status, *goal.tags],
                updated_at=goal.updated_at,
            )
        )
    return out


def _thread_nodes(root: Path) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    for thread in work_threads.list_threads(root, include_all=True)[:50]:
        node_id = f"thread:{thread.thread_id}"
        nodes.append(
            GraphNode(
                node_id=node_id,
                kind="thread",
                label=thread.title,
                summary=thread.next_action,
                ref=thread.thread_id,
                tags=["work-thread", thread.state, *thread.tags],
                updated_at=thread.updated_at,
            )
        )
        if thread.goal_id:
            edges.append(GraphEdge(node_id, f"goal:{thread.goal_id}", "owns-goal", 1.0))
    return nodes, edges


def _memory_nodes(root: Path) -> list[GraphNode]:
    out = []
    for item in memory_journal.filter_signals(root, include_sensitive=False)[:50]:
        text = str(item.get("text") or "")
        if not text:
            continue
        signal_id = str(item.get("signal_id") or item.get("id") or _short_id(text))
        out.append(
            GraphNode(
                node_id=f"memory:{signal_id}",
                kind="memory",
                label=text[:90],
                summary=str(item.get("category") or item.get("memory_type") or "memory"),
                ref=signal_id,
                tags=[str(item.get("memory_type") or "memory"), *(item.get("tags") or [])],
                updated_at=int(item.get("updated_at") or 0),
            )
        )
    return out


def _entity_nodes(root: Path) -> list[GraphNode]:
    out = []
    for record in entities.list_entities(root, include_private=False, limit=80):
        out.append(
            GraphNode(
                node_id=f"entity:{record.entity_id}",
                kind="entity",
                label=record.name,
                summary=f"{record.kind}; {record.mentions} mention(s)",
                ref=record.entity_id,
                tags=[record.kind, *record.tags],
                updated_at=record.updated_at,
            )
        )
    return out


def _artifact_nodes(root: Path) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    for artifact in artifact_studio.list_artifacts(root, limit=60):
        node_id = f"artifact:{artifact.artifact_id}"
        nodes.append(
            GraphNode(
                node_id=node_id,
                kind="artifact",
                label=artifact.name,
                summary=f"{artifact.kind}; {artifact.status}",
                ref=artifact.rel_path or artifact.path,
                tags=[artifact.kind, artifact.status, artifact.source],
                updated_at=artifact.updated_at,
            )
        )
        if artifact.thread_id:
            edges.append(GraphEdge(node_id, f"thread:{artifact.thread_id}", "attached-to-thread", 1.0))
        elif artifact.mission_id:
            edges.append(GraphEdge(node_id, f"goal:{artifact.mission_id}", "attached-to-goal", 1.0))
    return nodes, edges


def _skill_nodes(root: Path) -> list[GraphNode]:
    out = []
    for skill in skills.discover(root, include_disabled=True)[:35]:
        out.append(
            GraphNode(
                node_id=f"skill:{skill.name.lower()}",
                kind="skill",
                label=f"${skill.name}",
                summary=skill.description or skill.title,
                ref=str(skill.path),
                tags=["enabled" if skill.enabled else "blocked", skill.trust_level],
                updated_at=_mtime(skill.path),
            )
        )
    return out


def _tool_nodes() -> list[GraphNode]:
    out = []
    for schema in REGISTRY.schemas()[:45]:
        name = str(schema.get("name") or "")
        meta = schema.get("x_crypt") if isinstance(schema.get("x_crypt"), dict) else {}
        out.append(
            GraphNode(
                node_id=f"tool:{name}",
                kind="tool",
                label=name,
                summary=str(schema.get("description") or ""),
                ref=name,
                tags=[str(meta.get("capability") or ""), str(meta.get("risk") or "")],
            )
        )
    return out


def _file_nodes(root: Path) -> list[GraphNode]:
    out = []
    try:
        entries = sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:35]
    except OSError:
        return out
    for item in entries:
        if item.name.startswith(".") and item.name not in {".github", ".agents"}:
            continue
        try:
            updated = int(item.stat().st_mtime)
        except OSError:
            updated = 0
        out.append(
            GraphNode(
                node_id=f"file:{item.name}",
                kind="file",
                label=item.name,
                summary="folder" if item.is_dir() else item.suffix.lower().lstrip(".") or "file",
                ref=str(item),
                tags=["folder" if item.is_dir() else "file"],
                updated_at=updated,
            )
        )
    return out


def _overlap_edges(nodes: list[GraphNode]) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    token_map = {node.node_id: _node_tokens(node) for node in nodes}
    for index, left in enumerate(nodes):
        for right in nodes[index + 1:]:
            if left.kind == right.kind and left.kind in {"tool", "file"}:
                continue
            overlap = token_map[left.node_id] & token_map[right.node_id]
            if len(overlap) < 2:
                continue
            weight = min(1.0, 0.25 + len(overlap) * 0.15)
            edges.append(GraphEdge(left.node_id, right.node_id, "mentions", round(weight, 2)))
            if len(edges) >= MAX_GRAPH_EDGES:
                return edges
    return edges


def _unique_nodes(nodes: list[GraphNode]) -> list[GraphNode]:
    seen: set[str] = set()
    out: list[GraphNode] = []
    for node in nodes:
        if not node.node_id or node.node_id in seen:
            continue
        seen.add(node.node_id)
        out.append(node)
    out.sort(key=lambda node: (node.kind in {"goal", "thread", "entity", "artifact"}, node.updated_at), reverse=True)
    return out


def _unique_edges(edges: list[GraphEdge], valid_ids: set[str]) -> list[GraphEdge]:
    seen: set[tuple[str, str, str]] = set()
    out: list[GraphEdge] = []
    for edge in edges:
        if edge.source not in valid_ids or edge.target not in valid_ids or edge.source == edge.target:
            continue
        key = (edge.source, edge.target, edge.relation)
        reverse_key = (edge.target, edge.source, edge.relation)
        if key in seen or reverse_key in seen:
            continue
        seen.add(key)
        out.append(edge)
    out.sort(key=lambda edge: edge.weight, reverse=True)
    return out


def _edge_counts(edges: list[GraphEdge]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.source] = counts.get(edge.source, 0) + 1
        counts[edge.target] = counts.get(edge.target, 0) + 1
    return counts


def _node_tokens(node: GraphNode) -> set[str]:
    return _tokens(" ".join([node.kind, node.label, node.summary, " ".join(node.tags)]))


def _tokens(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9_.+-]{2,}", str(value or "").lower())
    return {word for word in words if word not in STOP_WORDS}


def _short_id(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _mtime(path: str | Path) -> int:
    try:
        return int(Path(path).stat().st_mtime)
    except OSError:
        return 0
