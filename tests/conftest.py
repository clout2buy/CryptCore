"""Shared pytest fixtures for Crypt tests.

Keeps tests fast and isolated:
- `workspace` provides a fresh temp dir + sets CRYPT_ROOT so resolve()
  is happy without scribbling on the user's real workspace.
- `clear_file_state` zeroes the read-before-edit table per test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Make the repo importable when pytest runs from any cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CRYPT_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _clear_file_state():
    from core import file_state

    file_state.clear()
    yield
    file_state.clear()
