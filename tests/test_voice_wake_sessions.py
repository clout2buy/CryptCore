from __future__ import annotations

from pathlib import Path

from core import settings, voice_wake_sessions


def test_voice_wake_sessions_track_wake_confirmation_and_preferences(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    started = voice_wake_sessions.record_event(workspace, "started", conversation_id="voice_1", voice="af_heart")
    heard = voice_wake_sessions.record_event(
        workspace,
        "transcript",
        text="Hey Crypt yeah do it, and make the voice sound more natural and shorter.",
        conversation_id=started.session_id,
        voice="af_heart",
    )
    interrupted = voice_wake_sessions.record_event(
        workspace,
        "interrupted",
        text="User cut in while audio was playing.",
        conversation_id=started.session_id,
        voice="af_heart",
    )

    assert heard.wake_phrase_hits == 1
    assert heard.confirmation_count >= 1
    assert heard.preference_count >= 1
    assert interrupted.interruption_count == 1

    snap = voice_wake_sessions.snapshot(workspace)
    assert snap["wakePhraseHits"] == 1
    assert snap["confirmationCount"] >= 1
    assert snap["preferenceCount"] >= 1
    assert "Voice Wake Session Layer" in voice_wake_sessions.prompt_section(workspace)


def test_voice_wake_sessions_persist_recent_sessions(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    voice_wake_sessions.record_event(workspace, "started", conversation_id="voice_a", voice="af_bella")
    voice_wake_sessions.record_event(workspace, "stopped", conversation_id="voice_a", voice="af_bella")
    voice_wake_sessions.record_event(workspace, "started", conversation_id="voice_b", voice="am_puck")

    sessions = voice_wake_sessions.list_sessions(workspace, include_all=True)
    assert [session.session_id for session in sessions[:2]] == ["voice_b", "voice_a"]
    assert sessions[0].active_voice == "am_puck"
