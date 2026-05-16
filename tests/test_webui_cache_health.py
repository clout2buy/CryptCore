from __future__ import annotations

from core import webui_cache_health


def test_webui_cache_health_contract_and_client_report():
    snapshot = webui_cache_health.snapshot()

    assert snapshot["required"] == 1
    assert any(store["key"] == "crypt.webui.chatSessions.v2" for store in snapshot["stores"])
    assert snapshot["clientHealth"] == "reported-by-browser"

    missing = webui_cache_health.assess_client({})
    assert missing["status"] == "warning"
    assert missing["issues"][0]["detail"] == "required browser cache store missing"

    oversized = webui_cache_health.assess_client({"crypt.webui.chatSessions.v2": {"count": 99}})
    assert oversized["status"] == "warning"
    assert "too many cached items" in oversized["issues"][0]["detail"]


def test_webui_cache_health_reports_corrupt_client_cache():
    report = webui_cache_health.assess_client({"crypt.webui.chatSessions.v2": {"corrupt": True}})

    assert report["status"] == "warning"
    assert report["issues"][0]["detail"] == "browser reported corrupt cache"
