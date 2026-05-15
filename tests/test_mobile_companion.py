from __future__ import annotations

from pathlib import Path

from core import mobile_companion


def test_mobile_companion_builds_badges_and_status(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    snap = mobile_companion.snapshot(
        workspace,
        {
            "personalOS": {"status": "attention", "summary": {"activeThreads": 3, "approvals": 2}},
            "memoryJournal": {"openLoopCount": 4},
            "artifactSummary": {"total": 7},
            "externalDrafts": {"pending": 2},
            "notifications": {"unread": 5},
        },
    )

    tabs = {tab["view"]: tab for tab in snap["tabs"]}
    assert snap["status"] == "attention"
    assert snap["statusText"] == "2 approval(s) waiting"
    assert tabs["missions"]["badge"] == "3"
    assert tabs["memory"]["badge"] == "4"
    assert tabs["files"]["badge"] == "7"
    assert snap["coreBadge"] == "5"
