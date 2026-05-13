from __future__ import annotations

from core import runtime
from tools import dispatch


def test_default_approval_mode_auto_approves_work_tools():
    previous = runtime.approval_mode()
    runtime.set_approval_mode(runtime.APPROVAL_EDITS)
    try:
        assert runtime.approval_label() == "auto-work"
        assert runtime.can_auto_approve("write_file") is True
        assert runtime.can_auto_approve("edit_file") is True
        assert runtime.can_auto_approve("multi_edit") is True
        assert runtime.can_auto_approve("bash") is True
        assert runtime.can_auto_approve("bash_start") is True
        assert runtime.can_auto_approve("open_file") is True
        assert runtime.can_auto_approve("web_search") is True
        assert runtime.can_auto_approve("web_fetch") is True
        assert runtime.can_auto_approve("spawn_agent") is False
    finally:
        runtime.set_approval_mode(previous)


def test_set_workspace_tool_requires_approval_in_noninteractive_auto_work(tmp_path):
    previous = runtime.approval_mode()
    runtime.configure(None, str(tmp_path), session=None)
    runtime.set_approval_mode(runtime.APPROVAL_EDITS)
    try:
        ok, msg = dispatch("set_workspace", {"path": str(tmp_path)}, render=False)
    finally:
        runtime.set_approval_mode(previous)

    assert ok is False
    assert "approval required" in msg
