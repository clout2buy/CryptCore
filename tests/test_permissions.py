"""Allow/deny rule grammar.

Locks the contract for `~/.crypt/permissions.json` so the precedence
(deny > allow > default) and glob semantics don't drift.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import permissions


@pytest.fixture
def rules_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Make `permissions.check()` read from a temp file we control."""
    f = tmp_path / "permissions.json"
    monkeypatch.setattr(permissions, "PERMISSIONS_PATH", f)
    monkeypatch.setattr(permissions, "_CACHE", None)
    monkeypatch.setattr(permissions, "_CACHE_MTIME", None)
    return f


def write(f: Path, allow=None, deny=None):
    f.write_text(json.dumps({"allow": allow or [], "deny": deny or []}))


def test_default_when_no_file(rules_file):
    assert permissions.check("bash", "git status") == ("default", None)


def test_allow_match(rules_file):
    write(rules_file, allow=["bash:git status*"])
    decision, rule = permissions.check("bash", "git status --short")
    assert decision == "allow"
    assert rule == "bash:git status*"


def test_deny_wins_over_allow(rules_file):
    write(rules_file, allow=["bash:rm *"], deny=["bash:rm -rf *"])
    decision, rule = permissions.check("bash", "rm -rf /tmp/x")
    assert decision == "deny"
    assert rule == "bash:rm -rf *"


def test_default_when_no_match(rules_file):
    write(rules_file, allow=["bash:git status*"])
    assert permissions.check("bash", "echo hi") == ("default", None)


def test_glob_question_mark(rules_file):
    write(rules_file, allow=["bash:l?"])
    assert permissions.check("bash", "ls")[0] == "allow"
    assert permissions.check("bash", "lll")[0] == "default"


def test_other_tool_unaffected(rules_file):
    write(rules_file, allow=["bash:*"])
    # An allow rule for bash must not bleed onto edit_file.
    assert permissions.check("edit_file", "main.py") == ("default", None)


def test_cache_invalidated_on_mtime_change(rules_file):
    write(rules_file, allow=["bash:foo*"])
    assert permissions.check("bash", "foo bar")[0] == "allow"

    # Rewrite with different rules; mtime changes → cache must reload.
    import os
    new_mtime = rules_file.stat().st_mtime + 5
    write(rules_file, allow=["bash:baz*"])
    os.utime(rules_file, (new_mtime, new_mtime))

    assert permissions.check("bash", "foo bar")[0] == "default"
    assert permissions.check("bash", "baz qux")[0] == "allow"


def test_malformed_json_does_not_crash(rules_file):
    rules_file.write_text("{ this is not json")
    # Should silently degrade to no rules, not raise into the dispatcher.
    assert permissions.check("bash", "anything") == ("default", None)
