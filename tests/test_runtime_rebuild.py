from __future__ import annotations

import os
import time
from pathlib import Path

from core import runtime_rebuild, settings, webui


def test_runtime_rebuild_plan_preserves_sessions_and_restart_command(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "launch_crypt_webui.bat").write_text("@echo off\n", encoding="utf-8")

    plan = runtime_rebuild.plan(workspace, reason="backend changed", changed_files=["core/webui.py"])

    assert "verify_core.ps1 -Quick" in "; ".join(plan.commands)
    assert plan.restart_command.endswith("launch_crypt_webui.bat")
    assert any("localStorage" in item for item in plan.preserve)
    assert plan.changed_files == ["core\\webui.py"] or plan.changed_files == ["core/webui.py"]


def test_runtime_rebuild_snapshot_detects_backend_change_after_record(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    core_dir = workspace / "core"
    core_dir.mkdir(parents=True)
    watched = core_dir / "webui.py"
    watched.write_text("print('old')\n", encoding="utf-8")

    runtime_rebuild.record(workspace, status="verified", checks=["scripts\\verify_core.ps1 -Quick"], restart_recommended=False)
    os.utime(watched, (time.time() + 5, time.time() + 5))
    snapshot = runtime_rebuild.snapshot(workspace)
    section = runtime_rebuild.prompt_section(workspace)

    assert snapshot["restartRecommended"] is True
    assert "Live Runtime Rebuild" in section
    assert "verify_core.ps1" in section


def test_webui_snapshot_includes_runtime_rebuild(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        snapshot = handler_obj._snapshot()
    finally:
        server.server_close()

    assert "runtimeRebuild" in snapshot
    assert "plan" in snapshot["runtimeRebuild"]
