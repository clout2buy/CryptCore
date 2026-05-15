from __future__ import annotations

import threading
from pathlib import Path

from core import browser_operator, settings, webui


def test_browser_operator_plans_local_visual_qa():
    plan = browser_operator.plan("Open the WebUI on 127.0.0.1 and take a desktop screenshot")

    assert plan.mode == "local-app-qa"
    assert "local-qa" in plan.actions
    assert "screenshot" in plan.actions
    assert plan.needs_visual_browser is True


def test_browser_operator_local_smoke_checks_webui(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        result = browser_operator.local_smoke(f"http://{host}:{port}/")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.ok is True
    assert result.status == 200
    assert result.title == "Crypt"
    assert {"http", "html", "title"} <= set(result.checks)
