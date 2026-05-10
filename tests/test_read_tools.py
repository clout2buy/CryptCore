from __future__ import annotations

import sys
import types

from core import artifact_lifecycle
from tools import read_file, read_media
from tools import edit_file
from tools import open_file
from tools import registry


def test_read_file_direct_call_accepts_absolute_path_outside_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("CRYPT_ROOT", str(workspace))

    out = read_file.run({"path": str(outside)})

    assert "hello" in out


def test_read_file_dispatch_requires_approval_outside_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("CRYPT_ROOT", str(workspace))

    ok, out = registry.dispatch("read_file", {"path": str(outside)}, render=False)

    assert ok is False
    assert "approval required" in out


def test_read_file_dispatch_auto_allows_workspace_path(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside = workspace / "inside.txt"
    inside.write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("CRYPT_ROOT", str(workspace))

    ok, out = registry.dispatch("read_file", {"path": str(inside)}, render=False)

    assert ok is True
    assert "hello" in out


def test_read_tool_classifiers_require_approval_outside_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("CRYPT_ROOT", str(workspace))

    assert read_file.classify({"path": str(outside)}) == "ask"
    assert read_media.classify({"path": str(outside)}) == "ask"


def test_open_file_auto_allows_only_tracked_generated_artifacts(monkeypatch, tmp_path):
    artifact_lifecycle.clear()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    generated = workspace / "artifact.txt"
    active = workspace / "artifact.html"
    source = workspace / "main.py"
    outside = tmp_path / "artifact.html"
    generated.write_text("<html></html>", encoding="utf-8")
    active.write_text("<html></html>", encoding="utf-8")
    source.write_text("print('hi')\n", encoding="utf-8")
    outside.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("CRYPT_ROOT", str(workspace))

    assert open_file.classify({"path": str(generated)}) == "ask"
    artifact_lifecycle.record_write(generated)
    artifact_lifecycle.record_write(active)
    assert open_file.classify({"path": str(generated)}) == "safe"
    assert open_file.classify({"path": str(active)}) == "ask"
    assert open_file.classify({"path": str(source)}) == "ask"
    assert open_file.classify({"path": str(outside)}) == "ask"


def test_read_media_pdf_outside_workspace_includes_extracted_text(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "guide.pdf"
    outside.write_bytes(b"%PDF-1.4\n% fake test pdf\n")
    monkeypatch.setenv("CRYPT_ROOT", str(workspace))

    class _Page:
        def extract_text(self):
            return "Exam objective text"

    class _Reader:
        pages = [_Page()]

    monkeypatch.setitem(
        sys.modules,
        "pypdf",
        types.SimpleNamespace(PdfReader=lambda path: _Reader()),
    )

    out = read_media.run({"path": str(outside)})

    assert out["__crypt_tool_result__"] is True
    text = "\n".join(block.get("text", "") for block in out["content"] if block.get("type") == "text")
    assert "Exam objective text" in text
    assert any(block.get("type") == "document" for block in out["content"])


def test_read_media_dispatch_requires_approval_outside_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "guide.pdf"
    outside.write_bytes(b"%PDF-1.4\n% fake test pdf\n")
    monkeypatch.setenv("CRYPT_ROOT", str(workspace))

    ok, out = registry.dispatch("read_media", {"path": str(outside)}, render=False)

    assert ok is False
    assert "approval required" in out


def test_range_covering_whole_file_counts_as_full_read(workspace):
    p = workspace / "deck.html"
    p.write_text("one\ntwo\n", encoding="utf-8")

    read_file.run({"path": str(p), "offset": 1, "limit": 2000})
    edit_file.run({"path": str(p), "old": "two", "new": "TWO"})

    assert p.read_text(encoding="utf-8") == "one\nTWO\n"
