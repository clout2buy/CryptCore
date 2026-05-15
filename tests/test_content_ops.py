from __future__ import annotations

from core import content_ops, external_drafts, settings


def test_content_ops_creates_channel_pieces_and_external_drafts(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    campaign = content_ops.plan(
        workspace,
        "Plan Reddit and YouTube content for the launch.",
        channels=["reddit", "youtube"],
    )

    assert campaign.channels == ["reddit", "youtube"]
    assert len(campaign.pieces) == 4
    assert all(piece.approval_required for piece in campaign.pieces)
    assert external_drafts.snapshot(workspace)["pending"] == 4
    snap = content_ops.snapshot(workspace)
    assert snap["pieces"] == 4
    assert snap["approvalRequired"] == 4
    assert "Content Operations" in content_ops.prompt_section(workspace)


def test_content_ops_records_metrics_and_dedupes_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    text = "Create content posts for Reddit about a new AI service."

    first = content_ops.ensure_for_prompt(workspace, text)
    second = content_ops.ensure_for_prompt(workspace, text)
    assert first.created is True
    assert second.created is False
    assert first.campaign is not None
    piece_id = first.campaign.pieces[0].piece_id

    updated = content_ops.record_metric(workspace, piece_id, views=100, clicks=9, leads=2)

    piece = next(piece for piece in updated.pieces if piece.piece_id == piece_id)
    assert piece.status == "measured"
    assert piece.metrics["views"] == 100
    assert content_ops.snapshot(workspace)["measured"] == 1
