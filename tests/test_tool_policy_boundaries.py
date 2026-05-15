from __future__ import annotations

from core import tool_policy


def test_tool_policy_classifies_safe_read_actions():
    boundary = tool_policy.classify_action("read_file", {"path": "app.py"})

    assert boundary.labels == ("safe",)
    assert boundary.risk == "low"
    assert boundary.requires_approval is False


def test_tool_policy_classifies_write_actions_as_approval_needed():
    boundary = tool_policy.classify_action("edit_file", {"path": "app.py"})

    assert "approval-needed" in boundary.labels
    assert boundary.requires_approval is True
    assert boundary.risk == "medium"


def test_tool_policy_warns_for_sensitive_external_actions():
    decision = tool_policy.preflight("web_fetch", {"url": "https://example.com?email=user@example.com"})

    assert decision.action == tool_policy.WARN
    assert decision.boundary is not None
    assert "sensitive" in decision.boundary.labels
    assert "external" in decision.boundary.labels


def test_tool_policy_warns_for_destructive_shell_commands():
    boundary = tool_policy.classify_action("bash", {"command": "git reset --hard"})

    assert "destructive" in boundary.labels
    assert boundary.requires_approval is True
    assert boundary.risk == "high"
