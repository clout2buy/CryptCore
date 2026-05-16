from __future__ import annotations

from core import accessibility_motion_audit


def test_accessibility_motion_audit_scores_webui_static_assets():
    snap = accessibility_motion_audit.snapshot()

    assert snap["total"] >= 6
    assert snap["score"] >= 0.9
    assert snap["blocking"] == 0
    categories = {check["category"] for check in snap["checks"]}
    assert {"keyboard", "contrast", "layout", "motion", "touch", "screen-reader"} <= categories
    assert any(check["check_id"] == "reduced-motion" and check["ok"] for check in snap["checks"])
    assert "Accessibility And Motion Audit" in accessibility_motion_audit.prompt_section()
