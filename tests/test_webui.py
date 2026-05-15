from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from core import (
    autonomy_contracts,
    capability_matrix,
    external_drafts,
    goals,
    settings,
    webui,
    webui_access,
    webui_backup,
    work_threads,
)


def test_webui_snapshot_endpoint(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        handler = webui.CryptWebHandler
        assert handler is not None
        snapshot = server.daemon.snapshot()
        assert snapshot["workspace"] == str(workspace.resolve())
        handler_obj = object.__new__(handler)
        handler_obj.server = server
        web_snapshot = handler_obj._snapshot()
        assert web_snapshot["workspace"] == str(workspace.resolve())
        assert "agentProfiles" in web_snapshot
        assert "agentDefinitions" in web_snapshot
        assert "agentTeamTemplates" in web_snapshot
        assert "voice" in web_snapshot
        assert "voiceConversation" in web_snapshot
        assert "workThreads" in web_snapshot
        assert "skillLifecycle" in web_snapshot
        assert "skillOutcomeAutoforge" in web_snapshot
        assert "artifactsPreview" in web_snapshot
        assert "artifactGroups" in web_snapshot
        assert "artifactSummary" in web_snapshot
        assert "artifactGraph" in web_snapshot
        assert "officeLayer" in web_snapshot
        assert "schedulesPreview" in web_snapshot
        assert "missionScheduler" in web_snapshot
        assert "monitorsPreview" in web_snapshot
        assert "memoryJournal" in web_snapshot
        assert "researchSources" in web_snapshot
        assert "dataImports" in web_snapshot
        assert "localSearch" in web_snapshot
        assert "workspaceMap" in web_snapshot
        assert "remoteAccess" in web_snapshot
        assert "capabilityMatrix" in web_snapshot
        assert "personaGovernance" in web_snapshot
        assert "autonomyContracts" in web_snapshot
        assert "approvalPolicy" in web_snapshot
        assert "liveReplay" in web_snapshot
        assert "jobQueue" in web_snapshot
        assert "externalDrafts" in web_snapshot
        assert "publicPosting" in web_snapshot
        assert "businessEntities" in web_snapshot
        assert "businessLaunch" in web_snapshot
        assert "contentOps" in web_snapshot
        assert "credentialVault" in web_snapshot
        assert "websitePipelines" in web_snapshot
        assert "revenueOps" in web_snapshot
        assert "browserRecordings" in web_snapshot
        assert "desktopRecordings" in web_snapshot
        assert "personalOS" in web_snapshot
        assert "mobileCompanion" in web_snapshot
        assert "toolCapabilityCards" in web_snapshot
        assert "smartModelRouter" in web_snapshot
        assert "providerHealth" in web_snapshot
        assert "modelUsageLedger" in web_snapshot
        assert "notifications" in web_snapshot
        assert "selfUpgradeSandbox" in web_snapshot
        assert "patchRisk" in web_snapshot
        assert web_snapshot["capabilityMatrix"]["total"] >= 10
        json.dumps(web_snapshot)
    finally:
        server.server_close()


def test_webui_remote_access_requires_token(tmp_path: Path):
    workspace = tmp_path / "repo"
    workspace.mkdir()

    with pytest.raises(ValueError, match="requires"):
        webui.make_server("0.0.0.0", 0, cwd=workspace)


def test_webui_access_token_cookie_and_scope_gate():
    access = webui_access.build("0.0.0.0", token="secret", scopes="read backup")

    missing = webui_access.authorize(access, method="GET", parsed=urlsplit("/"), headers={})
    assert missing.status.value == 401

    cookie = webui_access.authorize(access, method="GET", parsed=urlsplit("/?access_token=secret"), headers={})
    assert cookie.ok
    assert "crypt_access=secret" in cookie.set_cookie

    blocked = webui_access.authorize(
        access,
        method="POST",
        parsed=urlsplit("/api/prompt"),
        headers={"Authorization": "Bearer secret"},
    )
    assert blocked.status.value == 403


def test_webui_backup_restore_round_trip(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    goal = goals.add_goal("Track launch revenue", workspace=workspace, success_metric="weekly income logged")
    work_threads.ensure_for_goal(goal, prompt_text="track this every week")

    backup = webui_backup.export_backup(workspace)
    assert backup["summary"]["goals"] == 1
    assert not any("auth" in item["rel_path"].lower() for item in backup["files"])

    goals.goals_path().unlink()
    work_threads.threads_path().unlink()
    result = webui_backup.restore_backup(workspace, backup)

    assert result["count"] >= 2
    assert goals.list_goals(workspace, include_all=True)[0].title == "Track launch revenue"
    assert work_threads.list_threads(workspace, include_all=True)


def test_webui_int_helper():
    assert webui._int("12", 1) == 12
    assert webui._int("bad", 7) == 7


def test_webui_event_buffer(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        server.emit_event({"event": "demo", "text": "hello"})
        events = server.events_since(0)
        assert events[0]["event"] == "demo"
        assert events[0]["eventVersion"] == 1
        assert "ts" in events[0]
        assert json.dumps(events)
    finally:
        server.server_close()


def test_webui_event_sequence_stays_monotonic_after_buffer_wrap(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    server = webui.make_server("127.0.0.1", 0, cwd=workspace)
    try:
        for index in range(webui.MAX_EVENTS + 7):
            server.emit_event({"event": "demo", "index": index})

        assert len(server.events) == webui.MAX_EVENTS
        assert server.events[-1]["seq"] == webui.MAX_EVENTS + 7
        latest = server.events_since(webui.MAX_EVENTS + 6)
        assert len(latest) == 1
        assert latest[0]["index"] == webui.MAX_EVENTS + 6
    finally:
        server.server_close()


def test_webui_static_is_chat_first():
    html = resources.files("core.webui_static").joinpath("index.html").read_text(encoding="utf-8")
    script = resources.files("core.webui_static").joinpath("app.js").read_text(encoding="utf-8")

    assert "Crypt" in html
    assert "Core" in html
    assert "composer-shell" in html
    assert "voiceButton" in html
    assert "ttsTestButton" in html
    assert "composerAdvancedButton" in html
    assert "composerAdvanced" in html
    assert "providerSelect" in html
    assert "mobile-companion" in html
    assert "mobileStatusText" in html
    assert "data-view=\"missions\"" in html
    assert "data-view=\"agents\"" in html
    assert "agentTeamTemplates" in script
    assert "CHAT_STORE_KEY" in script
    assert "currentView: \"chat\"" in script
    assert "Self-Updating Memory" in script
    assert "Mission brain" in script
    assert "missionScheduler" in script
    assert "No schedules yet" in script
    assert "personaGovernance" in script
    assert "Artifact Studio" in script
    assert "officeLayer" in script
    assert "artifactGroups" in script
    assert "artifactSummary" in script
    assert "artifactGraph" in script
    assert "Artifact graph has no links yet" in script
    assert "No dashboard homework." in script
    assert "Autoforge Skill" in script
    assert "skillLifecycle" in script
    assert "skillOutcomeAutoforge" in script
    assert "No outcome patterns ready to promote" in script
    assert "workThreadUpdated" in script
    assert "memoryJournalUpdated" in script
    assert "missionCreated" in script
    assert "missionMatched" in script
    assert "intentRouted" in script
    assert "browserActivity" in script
    assert "desktopActivity" in script
    assert "missionStep" in script
    assert "activity-browser" in resources.files("core.webui_static").joinpath("styles.css").read_text(encoding="utf-8")
    assert "kokoro ready" in script
    assert "af_heart" in script
    assert "ChatGPT 5.5" in script
    assert "ChatGPT 5.3 Spark" in script
    assert "Crypt Max" not in script
    assert "Crypt Spark" not in script
    assert "live-timeline" in script
    assert "toolProgress" in script
    assert "thinkingDelta" in script
    assert "stopVoicePlayback" in script
    assert "flushVoiceInterim" in script
    assert "voiceTextForSpeech" in script
    assert "recordVoiceConversation" in script
    assert "voiceConversation" in script
    assert "shouldSpeakResponse" in script
    assert "pollEventsOnce" in script
    assert "pollSnapshotOnce" in script
    assert "startLivePulse" in script
    assert "renderLiveTimeline" in script
    assert "liveTurns" in script
    assert "registerEventSession" in script
    assert "sessionKey" in script
    assert "New Mission" not in script
    assert "Something Crypt should remember permanently" not in script
    assert "surface-dock" not in html
    assert "Skill Forge" not in html
    assert "Start a business" not in html
    assert "planner" not in html
    assert "data-prompt" not in html
    assert "approvalRequested" in script
    assert "coreFeatures" in script
    assert "capabilityMatrix" in script
    assert "Capability Matrix" in script
    assert "Local Search" in script
    assert "Workspace Map" in script
    assert "workspaceMap" in script
    assert "toolCapabilityCards" in script
    assert "Tool Arsenal" in script
    assert "Smart Model Router" in script
    assert "modelRouted" in script
    assert "Provider Health" in script
    assert "Usage Ledger" in script
    assert "Notification Center" in script
    assert "Personal OS" in script
    assert "Daily Command Surface" in script
    assert "syncMobileCompanion" in script
    assert "mobileCompanion" in script
    assert "Live Replay" in script
    assert "Self-Upgrade Sandbox" in script
    assert "Patch Risk" in script
    assert "Autonomy Contracts" in script
    assert "Approval Policy" in script
    assert "External Draft Queue" in script
    assert "Public Posting" in script
    assert "externalDraftCreated" in script
    assert "businessEntitiesUpdated" in script
    assert "Business registry" in script
    assert "businessLaunchUpdated" in script
    assert "Business launch" in script
    assert "contentOpsUpdated" in script
    assert "Content ops" in script
    assert "credentialVaultUpdated" in script
    assert "Credential Vault" in script
    assert "researchSourcesUpdated" in script
    assert "Data Import" in script
    assert "dataImports" in script
    assert "websitePipelineUpdated" in script
    assert "Site pipelines" in script
    assert "Revenue Ops" in script
    assert "Browser Recordings" in script
    assert "Desktop Recordings" in script
    assert "Persistent Jobs" in script
    assert "renderCurrentView" in script
    assert "syncEngineControls" in script
    assert "toggleComposerAdvanced" in script
    assert "modelMetadata" in script
    assert "data-message-id" in script
    assert "renderView = false" in script
    assert "Crypt runtime hints" not in html
    assert "data-view=\"providers\"" not in html
    assert "data-view=\"gateway\"" not in html


def test_capability_matrix_reports_runtime_state(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    matrix = capability_matrix.build(
        workspace,
        {
            "provider": "crypt",
            "model": "gpt-5.5",
            "authOk": True,
            "memoryJournal": {"longTermCount": 2, "workingCount": 1, "openLoopCount": 0},
            "voice": {"ready": False, "missing": ["kokoro-v1.0.onnx"]},
            "integrationsPreview": [{"configured": True, "enabled": False}],
            "agentProfiles": [{"name": "research"}],
            "skillsPreview": [{"name": "frontend-design"}],
            "workThreads": [{"state": "active"}],
            "remoteAccess": {"remote": False},
            "webui": {"url": "http://127.0.0.1:8765/"},
            "revenue": {"summary": {"revenue": 12.0, "leads": 3}},
            "schedulesPreview": [],
        },
    )
    data = matrix.to_dict()

    assert data["total"] >= 10
    assert data["ready"] >= 6
    assert any(item["id"] == "voice-loop" and item["status"] == "needs-setup" for item in data["capabilities"])
    assert any(item["id"] == "desktop-operator" and item["status"] == "approval-gated" for item in data["capabilities"])


def test_autonomy_contracts_select_safe_profile_for_external_actions():
    route = webui.intent_router.route("Post this on Reddit and email the leads.")
    contract = autonomy_contracts.select(route=route)

    assert contract.profile_id == "external-action"
    assert contract.default_action == "approval-gate"
    assert "all sends" in contract.approval_required
    assert "send without approval" in contract.forbidden
    assert "autonomy_contract=external-action" in autonomy_contracts.prompt_hint(contract)


def test_external_draft_queue_records_external_action(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    draft = external_drafts.draft_from_prompt(workspace, "Post this launch update on Reddit tomorrow.")
    assert draft is not None
    assert draft.kind == "reddit-post"
    assert draft.status == "pending-approval"
    assert "Reddit" in draft.title

    snap = external_drafts.snapshot(workspace)
    assert snap["pending"] == 1
    assert snap["drafts"][0]["draft_id"] == draft.draft_id

    approved = external_drafts.update_status(draft.draft_id, "approved", note="approved by user")
    assert approved.status == "approved"


def test_webui_core_features_include_hermes_style_sections(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config.json")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    snapshot = {
        "provider": "crypt",
        "model": "crypt-pro",
        "approval": "auto-work",
        "thinkingMode": "fast",
        "providers": [{"label": "Crypt OAuth", "status": "ready"}],
        "routes": [{"role": "builder", "status": "active"}],
        "webui": {"url": "http://127.0.0.1:8765/"},
    }
    features = webui.core_features(workspace, snapshot)
    labels = {feature["label"] for feature in features}

    assert {
        "Chat",
        "Sessions",
        "Profiles",
        "Agents",
        "Office",
        "Models",
        "Providers",
        "Skills",
        "Persona",
        "Memory",
        "Tools",
        "Plan",
        "Schedules",
        "Gateway",
        "Settings",
    } <= labels


def test_webui_autonomy_interval(monkeypatch):
    monkeypatch.delenv("CRYPT_WEBUI_AUTONOMY_INTERVAL_SECONDS", raising=False)
    assert webui._autonomy_interval() == webui.DEFAULT_AUTONOMY_INTERVAL_SECONDS

    monkeypatch.setenv("CRYPT_WEBUI_AUTONOMY_INTERVAL_SECONDS", "0")
    assert webui._autonomy_interval() == 0


def test_webui_prompt_intents_are_sanitized():
    assert webui._intent_hints(["web", "bad", "build", "web"]) == ["web", "build"]
    text = webui._prompt_with_context("Find leads", ["web", "auto"])

    assert text.startswith("Find leads")
    assert "Crypt runtime hints" in text
    assert "web research" in text


def test_webui_prompt_context_includes_auto_mission(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    decision = webui.mission_router.observe(workspace, "Build a client outreach business and track revenue weekly.")
    assert decision.goal is not None
    work_threads.ensure_for_goal(decision.goal, prompt_text=decision.goal.description)

    intent = webui.intent_router.route("Build this business")
    action = webui.clarification_policy.decide(intent)
    text = webui._prompt_with_context(
        "Build this business",
        [],
        mission=decision,
        intent=intent,
        action=action,
        workspace=workspace,
    )

    assert "autonomous mission" in text
    assert "intent=business" in text
    assert "action_policy=execute" in text
    assert "autonomy_contract=business-ops" in text
    assert "do not ask the user to manage missions manually" in text
    assert "Mission Brain" in text


def test_webui_prompt_context_includes_code_builder(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (workspace / "tests").mkdir()

    text = webui._prompt_with_context(
        "Fix the bug in core/app.py and run tests",
        [],
        workspace=workspace,
    )

    assert "Code Builder Loop" in text
    assert "inspect -> plan -> patch -> test -> review -> summarize -> commit-ready" in text
