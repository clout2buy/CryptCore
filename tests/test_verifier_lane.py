from __future__ import annotations

from pathlib import Path

from core import artifact_studio, evidence, goals, settings, verifier_lane, work_threads


def test_verifier_lane_records_pass_report_and_thread_evidence(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    evidence.clear()
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_app.py").write_text(
        "import pathlib\n"
        "import sys\n\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))\n\n"
        "from app import add\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    goal = goals.add_goal("Ship math fix", workspace=workspace, success_metric="tests pass")
    thread = work_threads.ensure_for_goal(goal, prompt_text="Fix app.py and verify")

    report = verifier_lane.run_verification(
        workspace,
        changed_files=["app.py", "tests/test_app.py"],
        thread_id=thread.thread_id,
    )
    refreshed = work_threads.list_threads(workspace, include_all=True)[0]
    studio = artifact_studio.snapshot(workspace)

    assert report.status == "PASS"
    assert Path(report.report_path).exists()
    assert evidence.latest_verifications()[-1].status == "PASS"
    assert refreshed.history[0]["source"] == "verifier-lane"
    assert studio["summary"]["missionLinked"] >= 1


def test_verifier_lane_reports_failed_syntax(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    evidence.clear()
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "broken.py").write_text("def nope(:\n", encoding="utf-8")

    report = verifier_lane.run_verification(workspace, changed_files=["broken.py"])

    assert report.status == "FAIL"
    assert report.checks[0].ok is False
    assert evidence.latest_verifications()[-1].status == "FAIL"


def test_verifier_lane_plans_browser_marker_for_web_changes(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "index.html").write_text("<html></html>\n", encoding="utf-8")

    checks = verifier_lane.plan_checks(workspace, changed_files=["index.html"], include_browser=True)

    assert checks[0].kind == "browser"
    assert checks[0].required is False
