"""Dependency graph linking artifacts, missions, memory, agents, and checks."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import agent_profiles, artifact_studio, evidence, goals, learning, settings, work_threads


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: str
    label: str
    status: str = ""
    detail: str = ""


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    label: str = ""


def build(cwd: str | Path, *, limit: int = 80) -> dict[str, Any]:
    root = Path(cwd).expanduser().resolve()
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    _add(nodes, GraphNode("workspace", "workspace", root.name or str(root), "active", str(root)))

    goal_rows = goals.list_goals(root, include_all=True)[:30]
    thread_rows = work_threads.list_threads(root, include_all=True)[:30]
    artifact_rows = artifact_studio.list_artifacts(root, limit=limit)
    lesson_rows = learning.list_lessons(root)[:12]
    agent_rows = agent_profiles.list_profiles(root)[:12]
    verification_rows = evidence.latest_verifications()[-8:]

    for goal in goal_rows:
        node_id = f"goal:{goal.goal_id}"
        _add(nodes, GraphNode(node_id, "mission", goal.title, goal.status, goal.success_metric))
        edges.append(GraphEdge("workspace", node_id, "contains", "mission"))

    for thread in thread_rows:
        node_id = f"thread:{thread.thread_id}"
        _add(nodes, GraphNode(node_id, "thread", thread.title, thread.state, thread.next_action))
        edges.append(GraphEdge("workspace", node_id, "tracks", "work thread"))
        if thread.goal_id:
            edges.append(GraphEdge(f"goal:{thread.goal_id}", node_id, "owns", "mission thread"))

    for artifact in artifact_rows:
        node_id = f"artifact:{artifact.artifact_id}"
        _add(nodes, GraphNode(node_id, "artifact", artifact.rel_path or artifact.name, artifact.status, artifact.kind))
        edges.append(GraphEdge("workspace", node_id, "contains", "artifact"))
        if artifact.thread_id:
            edges.append(GraphEdge(f"thread:{artifact.thread_id}", node_id, "produced", artifact.source))
        if artifact.mission_id:
            edges.append(GraphEdge(f"goal:{artifact.mission_id}", node_id, "requires", "mission artifact"))
        if artifact.status == "verified":
            check_id = f"check:artifact:{artifact.artifact_id}"
            _add(nodes, GraphNode(check_id, "check", f"verified {artifact.name}", "pass", _format_time(artifact.verified_at)))
            edges.append(GraphEdge(check_id, node_id, "verified", "artifact verification"))

    for index, lesson in enumerate(lesson_rows):
        node_id = f"memory:{lesson.lesson_id}"
        _add(nodes, GraphNode(node_id, "memory", f"Lesson {index + 1}", "active", lesson.text))
        target = _artifact_target(artifact_rows, lesson.text) or "workspace"
        edges.append(GraphEdge(node_id, target, "informs", "learned context"))

    for profile in agent_rows:
        node_id = f"agent:{profile.id}"
        _add(nodes, GraphNode(node_id, "agent", profile.name, profile.agent_type, profile.purpose))
        edges.append(GraphEdge("workspace", node_id, "can-use", profile.route_role))
        for thread in thread_rows[:6]:
            if profile.route_role and profile.route_role in {"builder", "planner", "reviewer"}:
                edges.append(GraphEdge(node_id, f"thread:{thread.thread_id}", "can-assist", profile.route_role))

    for index, result in enumerate(verification_rows):
        node_id = f"check:runtime:{index}"
        label = result.commands[0] if result.commands else "runtime verification"
        _add(nodes, GraphNode(node_id, "check", label, result.status.lower(), result.risk))
        target = _check_target(artifact_rows, result.commands) or "workspace"
        edges.append(GraphEdge(node_id, target, "verified" if result.status == "PASS" else "checked", result.status))

    release = _release_node(root)
    if release:
        _add(nodes, release)
        edges.append(GraphEdge("workspace", release.node_id, "release", "release checklist"))
        for artifact in artifact_rows[:8]:
            if "release" in artifact.rel_path.lower() or artifact.status == "verified":
                edges.append(GraphEdge(release.node_id, f"artifact:{artifact.artifact_id}", "includes", "release artifact"))

    deduped_edges = _dedupe_edges(edges, nodes)
    return {
        "summary": _summary(nodes, deduped_edges),
        "nodes": [asdict(node) for node in nodes.values()],
        "edges": [asdict(edge) for edge in deduped_edges],
    }


def prompt_section(cwd: str | Path) -> str:
    graph = build(cwd, limit=40)
    summary = graph["summary"]
    if not graph["nodes"]:
        return ""
    return (
        "# Artifact Dependency Graph\n"
        f"- nodes={summary['nodes']} edges={summary['edges']} artifacts={summary['artifacts']} "
        f"missions={summary['missions']} checks={summary['checks']}\n"
        "- Use the graph to explain why an artifact exists, what mission owns it, and what verified it."
    )


def _add(nodes: dict[str, GraphNode], node: GraphNode) -> None:
    if node.node_id not in nodes:
        nodes[node.node_id] = node


def _artifact_target(artifacts: list[artifact_studio.ArtifactRecord], text: str) -> str:
    lowered = str(text or "").lower()
    for artifact in artifacts:
        names = {artifact.rel_path.lower(), artifact.name.lower()}
        if any(name and name in lowered for name in names):
            return f"artifact:{artifact.artifact_id}"
    return ""


def _check_target(artifacts: list[artifact_studio.ArtifactRecord], commands: list[str]) -> str:
    text = " ".join(commands).lower()
    for artifact in artifacts:
        if artifact.rel_path.lower() in text or artifact.name.lower() in text:
            return f"artifact:{artifact.artifact_id}"
    return ""


def _release_node(root: Path) -> GraphNode | None:
    release_root = settings.APP_DIR / "release-train"
    checklist = root / ".crypt" / "release" / "release-checklist.md"
    if checklist.exists():
        return GraphNode("release:workspace", "release", "Workspace release checklist", "ready", str(checklist))
    if release_root.exists():
        return GraphNode("release:global", "release", "Release train", "ready", str(release_root))
    return None


def _dedupe_edges(edges: list[GraphEdge], nodes: dict[str, GraphNode]) -> list[GraphEdge]:
    out: list[GraphEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        if edge.source not in nodes or edge.target not in nodes:
            continue
        key = (edge.source, edge.target, edge.kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return out


def _summary(nodes: dict[str, GraphNode], edges: list[GraphEdge]) -> dict[str, int]:
    rows = list(nodes.values())
    return {
        "nodes": len(rows),
        "edges": len(edges),
        "artifacts": sum(1 for node in rows if node.kind == "artifact"),
        "missions": sum(1 for node in rows if node.kind == "mission"),
        "threads": sum(1 for node in rows if node.kind == "thread"),
        "memories": sum(1 for node in rows if node.kind == "memory"),
        "agents": sum(1 for node in rows if node.kind == "agent"),
        "checks": sum(1 for node in rows if node.kind == "check"),
    }


def _format_time(value: int) -> str:
    if not value:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))
