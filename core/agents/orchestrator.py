"""Model-visible orchestration guidance."""
from __future__ import annotations

import re


_BROAD_RE = re.compile(r"\b(full|entire|all|redesign|refactor|architecture|production|repo|codebase)\b", re.I)
_UI_RE = re.compile(r"\b(ui|terminal|frontend|screen|layout|design|transcript)\b", re.I)
_ARTIFACT_RE = re.compile(r"\b(html|website|app|canvas|animation|artifact|open|browser)\b", re.I)
_BUG_RE = re.compile(r"\b(bug|fail|fix|error|broken|regression)\b", re.I)
_AUDIT_RE = re.compile(
    r"\b(understand|audit|review|analy[sz]e|inspect|upgrade|improve|where\s+(?:we'?re|were)\s+at|what\s+we\s+can|recommend|roadmap|prioriti[sz]e)\b",
    re.I,
)
_AGENT_REQUIRED_RE = re.compile(
    r"\b(understand|audit|review|analy[sz]e|upgrade|improve|where\s+(?:we'?re|were)\s+at|what\s+we\s+can|recommend|roadmap|prioriti[sz]e|architecture|production|full|entire|codebase|repo)\b",
    re.I,
)
_NO_AGENT_RE = re.compile(r"\b(no agents?|do not use agents?|don't use agents?|without agents?|yourself only)\b", re.I)
_ACK_RE = re.compile(r"^\s*(ok|okay|yes|yeah|yep|focus|go ahead|do it|continue|sounds good)(?:\s+(?:ok|okay|yes|yeah|yep|focus|go ahead|do it|continue))*[\s.!]*$", re.I)
_PROMISE_RE = re.compile(
    r"\b(i'?ll|i will|let me|i can|best next move|next move|come back|start by|if you want)\b",
    re.I,
)
_INSPECTION_TOOLS = {
    "agent_output",
    "git",
    "glob",
    "grep",
    "list_agents",
    "list_files",
    "read_file",
    "read_media",
    "spawn_agent",
}


def classify(text: str) -> str:
    text = str(text or "")
    if _ARTIFACT_RE.search(text):
        return "artifact"
    if _UI_RE.search(text):
        return "ui"
    if _BROAD_RE.search(text):
        return "broad_edit"
    if _AUDIT_RE.search(text):
        return "repo_investigation"
    if _BUG_RE.search(text):
        return "focused_edit"
    if len(text) < 160:
        return "tiny"
    return "repo_investigation"


def guidance_for_turn(messages: list[dict], *, is_subagent: bool = False) -> str:
    if is_subagent:
        return ""
    text = task_text(messages)
    if not text:
        return ""
    kind = classify(text)
    if kind == "tiny":
        return ""
    lines = [
        "# Orchestration Guidance",
        f"- Runtime task class: {kind}.",
        "- Keep the immediate blocking path local; use agents only for independent side work.",
    ]
    if kind in {"broad_edit", "repo_investigation"}:
        if requires_agent(text):
            lines.append("- This request requires autonomous delegation: before final synthesis, spawn at least one explorer or planner agent unless the user explicitly said not to use agents.")
            lines.append("- Direct read/search tools are still useful locally, but they do not replace the required agent lane for broad repo understanding or upgrade audits.")
        else:
            lines.append("- Consider an explorer or planner subagent for independent repo discovery when it will reduce context load.")
        lines.append("- Do not answer with a promise to inspect later; inspect now.")
        lines.append("- Use a verifier subagent or focused checks before final completion claims.")
    elif kind == "ui":
        lines.append("- For UI work, preserve the existing ui_kit boundaries and verify rendered transcript behavior.")
    elif kind == "artifact":
        lines.append("- Write the artifact first, then open or verify it; avoid repeated blind rewrites.")
    elif kind == "focused_edit":
        lines.append("- Read the affected files, patch narrowly, and run the nearest focused check.")
    return "\n".join(lines)


def should_retry_text_only(messages: list[dict], assistant_msg: dict) -> bool:
    """Return True when the model promised an audit instead of doing it."""
    text = task_text(messages)
    if classify(text) not in {"repo_investigation", "broad_edit"}:
        return False
    successful = _successful_tool_names_since_last_request(messages)
    if requires_agent(text) and "spawn_agent" not in successful:
        response = _extract_text(assistant_msg)
        return bool(response.strip())
    if successful.intersection(_INSPECTION_TOOLS):
        return False
    response = _extract_text(assistant_msg)
    if not response.strip():
        return False
    return bool(_PROMISE_RE.search(response)) or len(response.split()) < 80


def tool_retry_message(messages: list[dict]) -> dict:
    text = task_text(messages)
    return {
        "role": "user",
        "content": [{
            "type": "text",
            "text": (
                "Crypt harness correction: the user asked for real repo understanding or an upgrade audit. "
                "Do not answer with a promise or a high-level preamble. Your next response must use tools now. "
                "For this class of request, spawn_agent with agent_type=explorer or planner is required unless "
                f"the user explicitly disabled agents. Task: {text!r}"
            ),
        }],
    }


def requires_agent(text: str) -> bool:
    text = str(text or "")
    return bool(_AGENT_REQUIRED_RE.search(text) and not _NO_AGENT_RE.search(text))


def task_text(messages: list[dict]) -> str:
    users = _real_user_texts(messages)
    if not users:
        return ""
    latest = users[-1]
    if _ACK_RE.match(latest) and len(users) >= 2:
        return users[-2]
    return latest


def _last_real_user_text(messages: list[dict]) -> str:
    texts = _real_user_texts(messages)
    return texts[-1] if texts else ""


def _real_user_texts(messages: list[dict]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            text = content.strip()
            if text and not text.startswith("Crypt harness correction:"):
                out.append(text)
            continue
        if isinstance(content, list):
            if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
                continue
            text = "\n".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
            if text and not text.startswith("Crypt harness correction:"):
                out.append(text)
    return out


def _successful_tool_names_since_last_request(messages: list[dict]) -> set[str]:
    start = _last_real_user_index(messages)
    tool_names: dict[str, str] = {}
    successes: set[str] = set()
    for msg in messages[start + 1:]:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        if msg.get("role") == "assistant":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id"):
                    tool_names[str(block["id"])] = str(block.get("name", ""))
        elif msg.get("role") == "user":
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and not block.get("is_error")
                ):
                    name = tool_names.get(str(block.get("tool_use_id", "")))
                    if name:
                        successes.add(name)
    return successes


def _last_real_user_index(messages: list[dict]) -> int:
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        ):
            continue
        text = _extract_text(msg)
        if text and not text.startswith("Crypt harness correction:"):
            return i
    return 0


def _extract_text(message: dict) -> str:
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
