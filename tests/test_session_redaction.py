from __future__ import annotations

import json

from core import session, settings


def test_session_persists_redacted_messages_and_metadata(monkeypatch, tmp_path):
    secret = "secret-token-12345"
    monkeypatch.setenv("CRYPT_API_KEY", secret)
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / ".crypt")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    sess = session.Session(cwd, provider="test", model="m")
    sess.record_message({
        "role": "user",
        "content": f"use {secret} carefully",
    })
    sess.record_message({
        "role": "assistant",
        "content": [{
            "type": "tool_use",
            "id": "toolu_1",
            "name": "write_file",
            "input": {"content": f"API_KEY={secret}"},
        }],
    })

    raw = sess.path.read_text(encoding="utf-8")
    assert secret not in raw
    assert "[redacted]" in raw
    assert sess.info().last_user == "use [redacted] carefully"
    assert sess.load_messages()[0]["content"] == "use [redacted] carefully"
    assert sess.load_messages()[1]["content"][0]["input"]["content"] == "API_KEY=[redacted]"


def test_compaction_snapshot_is_redacted(monkeypatch, tmp_path):
    secret = "compact-secret-12345"
    monkeypatch.setenv("CRYPT_TOKEN", secret)
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / ".crypt")
    cwd = tmp_path / "repo"
    cwd.mkdir()

    sess = session.Session(cwd, provider="test", model="m")
    sess.record_compaction(
        f"summary has {secret}",
        1,
        [{"role": "user", "content": [{"type": "text", "text": f"value {secret}"}]}],
    )

    raw = sess.path.read_text(encoding="utf-8")
    assert secret not in raw
    entries = [json.loads(line) for line in raw.splitlines()]
    compact = next(entry for entry in entries if entry["type"] == "compact")
    snapshot = next(entry for entry in entries if entry["type"] == "snapshot")
    assert compact["summary"] == "summary has [redacted]"
    assert snapshot["messages"][0]["content"][0]["text"] == "value [redacted]"
