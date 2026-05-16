from __future__ import annotations

from pathlib import Path

from core import eval_harness, settings


def _rich_snapshot():
    return {
        "businessLaunch": {"active": 1},
        "businessEntities": {"count": 2},
        "revenueOps": {"targets": 1},
        "contentOps": {"pieces": 4},
        "externalDrafts": {"pending": 1},
        "researchSources": {"total": 3},
        "dataImports": {"total": 1},
        "localSearch": {"documents": 5},
        "memoryJournal": {"longTermCount": 5, "openLoopCount": 2},
        "personaGovernance": {"status": "clear"},
        "skillOutcomeAutoforge": {"ready": 1},
        "browserRecordings": {"total": 2},
        "artifactGraph": {"summary": {"nodes": 2, "edges": 1}},
        "voice": {"ready": True},
        "voiceConversation": {"turnCount": 2, "interruptionCount": 1},
        "liveReplay": {"total": 2},
        "jobQueue": {"completed": 1},
        "notifications": {"unread": 1},
        "mobileCompanion": {"status": "ready"},
        "safetyIncidents": {"open": 0},
    }


def test_eval_harness_scores_agent_capability_categories(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    snap = eval_harness.snapshot(workspace, _rich_snapshot())

    assert snap["total"] >= 6
    assert snap["passing"] >= 5
    assert snap["overallScore"] > 0.75
    assert {"business", "research", "memory", "browser", "voice", "webui"} <= set(snap["categories"])
    assert "Evaluation Harness Expansion" in eval_harness.prompt_section(workspace, _rich_snapshot())


def test_eval_harness_writes_report(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    report = eval_harness.write_report(workspace, _rich_snapshot())

    assert report["overallScore"] > 0
    assert eval_harness.reports_path(workspace).exists()
