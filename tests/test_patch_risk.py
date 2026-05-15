from __future__ import annotations

from pathlib import Path

from core import patch_risk


def test_patch_risk_detects_ui_security_and_missing_tests(tmp_path: Path):
    report = patch_risk.classify(
        tmp_path,
        [
            "core/webui.py",
            "core/webui_static/app.js",
            "core/auth.py",
            "core/tool_policy.py",
        ],
    )

    assert report.risk == "high"
    assert report.ui == "medium"
    assert report.security == "medium"
    assert report.tests == "missing"
    assert any("node --check" in check for check in report.recommended_checks)


def test_patch_risk_lowers_when_tests_present(tmp_path: Path):
    report = patch_risk.classify(tmp_path, ["core/scheduler.py", "tests/test_scheduler.py"])

    assert report.tests == "present"
    assert report.risk in {"low", "medium"}
    assert "pytest" in report.recommended_checks


def test_patch_risk_prompt_section_is_empty_without_changes(tmp_path: Path):
    section = patch_risk.prompt_section(tmp_path)

    assert section == ""
