from __future__ import annotations

from pathlib import Path

from core import external_drafts, external_receipts, public_posting, settings


def test_external_receipts_record_draft_approval(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    draft = external_drafts.create_draft(
        workspace,
        kind="email",
        title="Send launch email",
        target="email",
        content="Draft copy",
    )
    external_drafts.update_status(draft.draft_id, "approved", note="send this")

    snapshot = external_receipts.snapshot(workspace)
    receipt = snapshot["receipts"][0]
    assert snapshot["approved"] == 1
    assert receipt["external_ref"] == draft.draft_id
    assert receipt["before_state"] == "pending-approval"
    assert receipt["after_state"] == "approved"
    assert "revert" in receipt["rollback_hint"].lower() or "correction" in receipt["rollback_hint"].lower()
    assert "External Action Receipts" in external_receipts.prompt_section(workspace)


def test_external_receipts_record_publication(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    post = public_posting.create_post(workspace, platform="reddit", title="Launch", content="No big claims.")
    approved = public_posting.approve(workspace, post.post_id, note="looks good")
    public_posting.mark_published(workspace, approved.post_id, url="https://reddit.com/r/test/post")

    receipts = external_receipts.snapshot(workspace)["receipts"]
    assert any(receipt["source"] == "public-posting" for receipt in receipts)
    assert any(receipt["after_state"] == "published" for receipt in receipts)
