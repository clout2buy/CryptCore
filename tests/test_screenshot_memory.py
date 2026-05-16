from __future__ import annotations

from pathlib import Path

from core import browser_recorder, screenshot_memory, settings


def test_screenshot_memory_ingests_browser_recordings(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    screenshot = workspace / "screens" / "chat.png"
    screenshot.parent.mkdir()
    screenshot.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    recording = browser_recorder.start_recording(workspace, "http://127.0.0.1:8765/", title="Crypt chat", note="Chat UI looked stable.")
    browser_recorder.add_screenshot(workspace, recording.recording_id, screenshot, note="Chat screenshot captured.")

    snap = screenshot_memory.snapshot(workspace)

    assert snap["total"] == 1
    assert snap["active"] == 1
    assert snap["bySource"]["browser"] == 1
    assert snap["annotations"][0]["screenshot"].endswith("screens/chat.png")
    assert "Screenshot Annotation Memory" in screenshot_memory.prompt_section(workspace)


def test_screenshot_memory_observes_chat_visual_feedback(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    annotation = screenshot_memory.observe_feedback(
        workspace,
        "The chat screenshot is flickering and the panel is too cluttered.",
        source="chat",
    )

    assert annotation is not None
    assert annotation.severity == "warning"
    assert annotation.defect.startswith("flicker")
    assert "polling" in annotation.recommendation.lower() or "refresh" in annotation.recommendation.lower()
    snap = screenshot_memory.snapshot(workspace)
    assert snap["defects"] == 1
    assert "flicker" in screenshot_memory.prompt_section(workspace)
