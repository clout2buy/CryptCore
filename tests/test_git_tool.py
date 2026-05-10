from __future__ import annotations

from core import runtime
from tools import git as git_tool


def test_git_tool_non_repo_returns_guidance(tmp_path):
    runtime.configure(None, str(tmp_path), session=None)

    out = git_tool.run({"action": "diff"})

    assert "not inside a git repository" in out
    assert "Switch the workspace to a repo folder" in out
