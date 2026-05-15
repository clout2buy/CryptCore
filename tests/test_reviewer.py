from __future__ import annotations

import shutil
from pathlib import Path

from core import reviewer


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def test_reviewer_catches_seeded_unsafe_code_and_missing_tests(tmp_path: Path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    (before / "app.py").write_text("def parse(value):\n    return int(value)\n", encoding="utf-8")
    (before / "tests").mkdir()
    (before / "tests" / "test_app.py").write_text("def test_parse():\n    assert True\n", encoding="utf-8")
    _copy_tree(before, after)
    (after / "app.py").write_text(
        "def parse(value):\n"
        "    try:\n"
        "        return eval(value)\n"
        "    except Exception:\n"
        "        pass\n",
        encoding="utf-8",
    )

    findings = reviewer.review_changes(before, after, changed_files=["app.py"])
    titles = {finding.title for finding in findings}

    assert "[P1] Dynamic code execution introduced" in titles
    assert "[P2] Broad exception is silently swallowed" in titles
    assert "[P2] Production code changed without test changes" in titles


def test_reviewer_flags_ui_quality_regressions(tmp_path: Path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    (before / "styles.css").write_text(".title { font-size: 18px; }\n", encoding="utf-8")
    _copy_tree(before, after)
    (after / "styles.css").write_text(
        ".title { font-size: 5vw; transition: all .2s ease; }\n",
        encoding="utf-8",
    )

    findings = reviewer.review_changes(before, after, changed_files=["styles.css"])
    titles = {finding.title for finding in findings}

    assert "[P3] Viewport-scaled font size" in titles
    assert "[P3] Transition-all can animate layout accidentally" in titles


def test_reviewer_prompt_section_names_checks():
    section = reviewer.prompt_section()

    assert "Reviewer Lane" in section
    assert "regressions" in section
    assert "UI quality" in section
