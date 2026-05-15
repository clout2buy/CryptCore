from __future__ import annotations

import pytest

from core import external_drafts, public_posting, research_sources, settings


def test_public_posting_requires_citations_for_claims_and_queues_draft(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    post = public_posting.create_post(
        workspace,
        platform="reddit",
        title="Launch proof",
        content="Our workflow improves lead response by 25% according to the launch report.",
    )

    assert post.status == "needs-citations"
    assert any(check.startswith("FAIL") for check in post.checks)
    assert external_drafts.snapshot(workspace)["pending"] == 1


def test_public_posting_citations_approval_and_publish_log(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    post = public_posting.create_post(
        workspace,
        platform="twitter",
        content="New launch note with research-backed workflow.",
        citations=["https://example.com/source"],
    )
    approved = public_posting.approve(workspace, post.post_id, note="looks good")
    published = public_posting.mark_published(workspace, post.post_id, url="https://x.com/demo/status/1")

    assert post.platform == "x"
    assert post.status == "pending-approval"
    assert approved.status == "approved"
    assert published.status == "published"
    assert research_sources.snapshot(workspace)["total"] == 1
    assert public_posting.snapshot(workspace)["published"] == 1
    assert "Public Posting Flow" in public_posting.prompt_section(workspace)


def test_public_posting_rejects_non_url_publish_log(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    post = public_posting.create_post(workspace, platform="blog", content="Simple update.")

    with pytest.raises(ValueError, match="http"):
        public_posting.mark_published(workspace, post.post_id, url="not-live")
