from __future__ import annotations

import json
from pathlib import Path

from core import target_eval
from core.api import TurnEnd


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_review_flags_return_contract_change_without_targeted_tests(tmp_path: Path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    _write(
        before / "services" / "leveling.py",
        "class LevelingService:\n"
        "    async def add_message_xp(self) -> tuple[int, bool]:\n"
        "        return 1, False\n",
    )
    _write(
        after / "services" / "leveling.py",
        "class LevelingService:\n"
        "    async def add_message_xp(self) -> tuple[int, bool] | None:\n"
        "        return None\n",
    )
    _write(after / "tests" / "test_xp_math.py", "def test_math():\n    assert 1 + 1 == 2\n")

    findings = target_eval.review_changes(before, after)

    assert any("return contract changed" in finding.title for finding in findings)


def test_review_allows_return_contract_when_tests_reference_function(tmp_path: Path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    _write(
        before / "services" / "leveling.py",
        "async def add_message_xp() -> tuple[int, bool]:\n    return 1, False\n",
    )
    _write(
        after / "services" / "leveling.py",
        "async def add_message_xp() -> tuple[int, bool] | None:\n    return None\n",
    )
    _write(after / "tests" / "test_leveling.py", "def test_add_message_xp_cooldown():\n    pass\n")

    findings = target_eval.review_changes(before, after)

    assert not any("return contract changed" in finding.title for finding in findings)


def test_review_flags_packaging_that_omits_top_level_modules(tmp_path: Path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    _write(after / "bot.py", "class Bot:\n    pass\n")
    _write(after / "main.py", "def main():\n    pass\n")
    _write(after / "core" / "__init__.py", "")
    _write(
        after / "pyproject.toml",
        "[project]\nname='demo'\nversion='0.1.0'\n"
        "[tool.setuptools.packages.find]\ninclude=['core*']\n",
    )

    findings = target_eval.review_changes(before, after)

    assert any("Packaging metadata omits top-level modules" in finding.title for finding in findings)
    assert any("console script" in finding.title for finding in findings)


def test_review_flags_test_helper_that_copies_logic(tmp_path: Path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    _write(
        after / "tests" / "test_config.py",
        "def _get_bool_iso(raw: str) -> bool:\n"
        "    \"\"\"Call the same logic as production.\"\"\"\n"
        "    return raw.strip().lower() in {'1', 'true'}\n",
    )

    findings = target_eval.review_changes(before, after)

    assert any("duplicates implementation" in finding.title for finding in findings)


def test_trace_forbidden_access_is_reported(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps({
            "event": "tool_start",
            "tool": "read_file",
            "args": {"path": ".env"},
        }) + "\n",
        encoding="utf-8",
    )

    assert target_eval.trace_accessed_paths(trace) == [".env"]
    findings = target_eval.review_changes(
        tmp_path / "before",
        tmp_path / "after",
        trace_path=trace,
        forbidden_accessed=[".env"],
    )
    assert any("Forbidden file" in finding.title for finding in findings)


def test_cleanup_removes_only_new_generated_artifacts(tmp_path: Path):
    root = tmp_path / "repo"
    existing = root / "__pycache__"
    existing.mkdir(parents=True)
    (existing / "old.pyc").write_bytes(b"old")
    before = target_eval._collect_generated_artifacts(root)
    new_cache = root / ".pytest_cache"
    new_cache.mkdir()
    (new_cache / "README.md").write_text("cache", encoding="utf-8")

    removed = target_eval.cleanup_generated_artifacts(root, before)

    assert ".pytest_cache" in removed
    assert existing.exists()
    assert not new_cache.exists()


def test_cleanup_removes_new_build_release_artifacts(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "dist").mkdir(parents=True)
    (root / "dist" / "demo.whl").write_bytes(b"wheel")
    (root / "build").mkdir()
    (root / "build" / "tmp.txt").write_text("build", encoding="utf-8")
    (root / "demo.egg-info").mkdir()
    (root / "demo.egg-info" / "PKG-INFO").write_text("metadata", encoding="utf-8")

    removed = target_eval.cleanup_generated_artifacts(root, existing=set())

    assert "dist" in removed
    assert "build" in removed
    assert "demo.egg-info" in removed
    assert not (root / "dist").exists()
    assert not (root / "build").exists()
    assert not (root / "demo.egg-info").exists()


class _WritesGeneratedArtifactProvider:
    name = "fake"
    model = "fake-model"
    is_oauth = False
    context_window = 128_000

    def __init__(self) -> None:
        self.calls = 0

    def stream_turn(self, messages, tools, system):
        self.calls += 1
        if self.calls == 1:
            yield TurnEnd(
                stop_reason="tool_use",
                message={
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_cache",
                            "name": "write_file",
                            "input": {"path": ".pytest_cache/README.md", "content": "cache"},
                        },
                        {
                            "type": "tool_use",
                            "id": "call_src",
                            "name": "write_file",
                            "input": {"path": "app.py", "content": "print('ok')\n"},
                        },
                    ],
                },
            )
            return
        yield TurnEnd(
            stop_reason="end_turn",
            message={"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        )


def test_run_target_cleans_artifacts_and_writes_report(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    report = target_eval.run_target(
        _WritesGeneratedArtifactProvider(),
        cwd=repo,
        checks=["python -c \"import pathlib; assert pathlib.Path('app.py').exists()\""],
        output_root=tmp_path / "runs",
        max_turns=5,
    )

    assert report.checks[0].ok is True
    assert ".pytest_cache/README.md" in report.removed_artifacts
    assert not (repo / ".pytest_cache").exists()
    assert "app.py" in report.changed_files
    assert Path(report.trace_path).exists()
    assert (Path(report.output_dir) / "report.json").exists()
