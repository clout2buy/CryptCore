from __future__ import annotations

from pathlib import Path

from core import settings, trust_calibration


def test_trust_calibration_defaults_execute_for_safe_code(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    decision = trust_calibration.decide(workspace, "fix the tests and push the code", intent="code", risk="medium")

    assert decision.domain == "code"
    assert decision.action == "execute"
    assert decision.approval_required is False


def test_trust_calibration_learns_caution_for_external_actions(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    signal = trust_calibration.observe(workspace, "ask before you post anything to reddit", intent="external_action")
    decision = trust_calibration.decide(workspace, "post this on reddit", intent="external_action", risk="high")

    assert signal is not None
    assert signal.delta < 0
    assert decision.domain == "external"
    assert decision.action == "draft"
    assert decision.approval_required is True


def test_trust_calibration_prompt_and_snapshot(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    trust_calibration.observe(workspace, "go all out on the UI and handle it", intent="ui")

    snap = trust_calibration.snapshot(workspace)
    text = trust_calibration.prompt_section(workspace, "make the UI better", intent="ui")

    assert snap["averageInitiative"] >= 3
    assert snap["signals"]
    assert "User Trust Calibration" in text
    assert "domain=ui" in text
