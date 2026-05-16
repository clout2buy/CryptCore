from __future__ import annotations

from pathlib import Path

from core import business_crm, settings


def test_business_crm_tracks_contacts_opportunities_and_followups(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    contact = business_crm.upsert_contact(
        workspace,
        name="Acme Buyer",
        email="buyer@acme.test",
        status="lead",
        next_action="Draft a local proposal.",
    )
    opportunity = business_crm.add_opportunity(
        workspace,
        contact_id=contact.contact_id,
        title="Acme starter package",
        value_usd=500,
        stage="qualified",
        probability=0.4,
    )
    business_crm.log_interaction(workspace, contact_id=contact.contact_id, channel="email", summary="Intro call booked.")

    snapshot = business_crm.snapshot(workspace)

    assert opportunity.stage == "qualified"
    assert snapshot["contacts"] == 1
    assert snapshot["opportunities"] == 1
    assert snapshot["pipelineValueUsd"] == 500
    assert snapshot["weightedPipelineUsd"] == 200
    assert snapshot["followUps"] == 1
    assert "Local Business CRM" in business_crm.prompt_section(workspace)


def test_business_crm_observes_lead_from_chat(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    observed = business_crm.observe_text(
        workspace,
        "Lead named Jordan needs a proposal for $250. Email jordan@example.com and follow up tomorrow.",
    )
    snapshot = business_crm.snapshot(workspace)

    assert observed.changed is True
    assert snapshot["contacts"] == 1
    assert snapshot["opportunities"] == 1
    assert snapshot["contactPreview"][0]["email"] == "jordan@example.com"
