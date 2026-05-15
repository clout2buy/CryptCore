from __future__ import annotations

from pathlib import Path

from core import artifact_studio, data_importer, goals, memory_journal, settings


def test_data_importer_imports_csv_as_artifact_and_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    csv_path = workspace / "leads.csv"
    csv_path.write_text("name,email\nAva,ava@example.com\nNoah,noah@example.com\n", encoding="utf-8")

    record = data_importer.import_file(workspace, csv_path)
    snap = data_importer.snapshot(workspace)

    assert record.kind == "csv"
    assert record.rows == 2
    assert record.columns == ["name", "email"]
    assert record.artifact_id
    assert record.memory_changed is True
    assert snap["total"] == 1
    assert artifact_studio.snapshot(workspace)["summary"]["total"] == 1
    memory = memory_journal.snapshot(workspace)
    assert memory["workingCount"] + memory["longTermCount"] >= 1
    assert "# Data Imports" in data_importer.prompt_section(workspace)


def test_data_importer_detects_browser_json_and_mission_notes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    browser_export = workspace / "browser-history.json"
    browser_export.write_text(
        '{"history":[{"url":"https://example.com","title":"Example","visited":"today"}]}',
        encoding="utf-8",
    )
    mission_note = workspace / "mission-note.md"
    mission_note.write_text("# Goal\nNext action: launch the tracker by Friday.\n", encoding="utf-8")

    browser = data_importer.import_file(workspace, browser_export, destination="entities")
    mission = data_importer.import_file(workspace, mission_note)

    assert browser.kind == "browser-export"
    assert "history" in browser.keys
    assert mission.kind == "note"
    assert mission.mission_id
    assert goals.list_goals(workspace)[0].goal_id == mission.mission_id
