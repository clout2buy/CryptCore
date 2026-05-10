from __future__ import annotations

from pathlib import Path

import pytest

from tools import write_file


def test_write_file_rejects_incomplete_html_document(workspace: Path):
    target = workspace / "broken.html"

    with pytest.raises(ValueError, match="incomplete HTML"):
        write_file.run({"path": str(target), "content": "<!doctype html><html><body><button id=\"x\""})

    assert not target.exists()


def test_write_file_allows_complete_html_document(workspace: Path):
    target = workspace / "ok.html"

    out = write_file.run({
        "path": str(target),
        "content": "<!doctype html><html><body><button id=\"x\">Go</button></body></html>",
    })

    assert out == "created ok.html"
    assert target.exists()
