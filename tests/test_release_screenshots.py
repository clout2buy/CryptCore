from __future__ import annotations

from pathlib import Path

from core import artifact_studio, release_screenshots, settings


def test_release_screenshots_plans_desktop_mobile(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    output = tmp_path / "release"

    manifest = release_screenshots.plan(
        workspace,
        release_id="phase-73",
        output_dir=output,
        url="http://127.0.0.1:8765/",
    )

    assert {target.name for target in manifest.targets} == {"desktop", "mobile"}
    assert all(target.status == "planned" for target in manifest.targets)
    assert (output / "screenshot-plan.json").exists()
    assert (output / "screenshot-plan.md").exists()
    assert any("PLANNED desktop" in item for item in release_screenshots.checklist_items(workspace, output_dir=output))
    assert artifact_studio.snapshot(workspace)["summary"]["total"] == 1


def test_release_screenshots_registers_captured_image(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    output = tmp_path / "release"
    image = output / "screenshots" / "desktop-1440x960.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"fakepng")

    manifest = release_screenshots.register(
        workspace,
        image,
        release_id="phase-73",
        output_dir=output,
        viewport="desktop",
        note="desktop smoke",
    )

    assert release_screenshots.captured_count(workspace, output_dir=output) == 1
    assert manifest.targets[0].status == "captured"
    assert any("CAPTURED desktop" in item for item in release_screenshots.checklist_items(workspace, output_dir=output))
    artifacts = artifact_studio.snapshot(workspace)["artifacts"]
    assert any(item["kind"] == "screenshot" and item["status"] == "verified" for item in artifacts)
