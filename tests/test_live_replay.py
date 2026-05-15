from __future__ import annotations

from core import live_replay, settings, webui


def test_live_replay_records_tool_and_browser_events(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    live_replay.record_event(
        workspace,
        {"event": "toolResult", "seq": 1, "tool": "read_file", "callId": "call_1", "ok": True, "text": "read README"},
    )
    live_replay.record_event(
        workspace,
        {"event": "browserActivity", "seq": 2, "text": "captured screenshot", "url": "http://127.0.0.1:8765/"},
    )

    snap = live_replay.snapshot(workspace)
    assert snap["total"] == 2
    assert snap["tools"] == 1
    assert snap["browser"] == 1
    assert "Live Replay" in live_replay.prompt_section(workspace)


def test_webui_emit_event_persists_replay(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        server.emit_event({"event": "toolResult", "tool": "bash", "callId": "call_2", "ok": False, "text": "failed"})
        snap = live_replay.snapshot(workspace)
        assert snap["total"] == 1
        assert snap["items"][0]["event"] == "toolResult"
    finally:
        server.server_close()
