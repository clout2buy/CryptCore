from __future__ import annotations

from pathlib import Path

from core import memory_journal, settings, voice_conversation


def test_voice_conversation_records_transcript_reply_and_interruption(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    started = voice_conversation.record_event(workspace, "started")
    heard = voice_conversation.record_event(
        workspace,
        "transcript",
        text="I need Crypt to remember that voice answers should be short.",
        conversation_id=started.conversation_id,
    )
    replied = voice_conversation.record_event(workspace, "reply", text="Got it. Short voice replies by default.")
    interrupted = voice_conversation.record_event(workspace, "interrupted", text="User cut in.")

    assert heard.turn_count == 1
    assert replied.last_reply_text == "Got it. Short voice replies by default."
    assert interrupted.interruption_count == 1
    assert voice_conversation.snapshot(workspace)["turnCount"] == 1
    assert memory_journal.snapshot(workspace)["longTermCount"] + memory_journal.snapshot(workspace)["workingCount"] >= 1
    assert "Voice Conversation Mode" in voice_conversation.prompt_section(workspace)


def test_voice_conversation_unknown_events_default_to_transcript(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    convo = voice_conversation.record_event(workspace, "weird", text="hello")

    assert convo.status == "heard"
    assert convo.events[0].event == "transcript"
