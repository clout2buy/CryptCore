from __future__ import annotations

import json
import time

from core import auth, oauth, openai_oauth, settings, tracing


def test_provider_auth_records_do_not_clobber_each_other(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(auth, "AUTH_PATH", tmp_path / "auth.json")

    auth.save_provider("anthropic", {"type": "oauth", "access": "anthropic-token"})
    auth.save_provider("openai-codex", {
        "type": "openai-codex",
        "access": "chatgpt-token",
        "refresh": "refresh",
        "expires": int(time.time() * 1000) + 60_000,
        "account_id": "account-123",
        "email": "me@example.com",
        "plan": "pro",
    })

    assert auth.load_provider("anthropic")["access"] == "anthropic-token"
    cred = auth.resolve_openai_codex()

    assert cred is not None
    assert cred.token == "chatgpt-token"
    assert cred.account_id == "account-123"
    assert cred.email == "me@example.com"
    assert cred.plan == "pro"


def test_legacy_anthropic_auth_file_still_resolves(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(auth, "AUTH_PATH", tmp_path / "auth.json")
    auth.save({"type": "oauth", "access": "anthropic-token"})

    cred = auth.resolve_anthropic()

    assert cred is not None
    assert cred.token == "anthropic-token"


def test_expired_anthropic_oauth_refreshes_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(auth, "AUTH_PATH", tmp_path / "auth.json")
    auth.save_provider("anthropic", {
        "type": "oauth",
        "access": "old-token",
        "refresh": "refresh-token",
        "expires": 1,
        "email": "me@example.com",
        "plan": "max",
    })

    monkeypatch.setattr(oauth, "refresh", lambda token: {
        "access_token": "new-token",
        "refresh_token": f"{token}-new",
        "expires_in": 3600,
    })

    cred = auth.resolve_anthropic()

    assert cred is not None
    assert cred.token == "new-token"
    saved = auth.load_provider("anthropic")
    assert saved["access"] == "new-token"
    assert saved["refresh"] == "refresh-token-new"
    assert saved["email"] == "me@example.com"
    assert saved["plan"] == "max"


def test_expired_openai_codex_oauth_refreshes_claims(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(auth, "AUTH_PATH", tmp_path / "auth.json")
    auth.save_provider("openai-codex", {
        "type": "openai-codex",
        "access": "old-chatgpt-token",
        "refresh": "refresh-token",
        "expires": 1,
        "account_id": "old-account",
        "email": "old@example.com",
        "plan": "plus",
    })

    monkeypatch.setattr(openai_oauth, "refresh", lambda token: {
        "access_token": "new-chatgpt-token",
        "refresh_token": f"{token}-new",
        "expires_in": 3600,
        "account_id": "account-456",
        "claims": {"email": "new@example.com"},
        "plan": "pro",
    })

    cred = auth.resolve_openai_codex()

    assert cred is not None
    assert cred.token == "new-chatgpt-token"
    assert cred.account_id == "account-456"
    assert cred.email == "new@example.com"
    assert cred.plan == "pro"
    saved = auth.load_provider("openai-codex")
    assert saved["refresh"] == "refresh-token-new"


def test_gemini_resolver_uses_api_key_before_oauth(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(auth, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GEMINI_PROJECT_ID", "project-123")

    cred = auth.resolve_gemini()

    assert cred is not None
    assert cred.kind == "api"
    assert cred.token == "gemini-key"
    assert cred.project_id == "project-123"


def test_gemini_resolver_does_not_use_adc_unless_requested(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(auth, "AUTH_PATH", tmp_path / "auth.json")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    adc = auth.Credential(kind="oauth", token="adc-token", project_id="adc-project")

    monkeypatch.setattr(auth, "_resolve_adc_gemini", lambda: adc)

    assert auth.resolve_gemini() is None
    assert auth.resolve_gemini(include_adc=True) == adc


def test_gemini_stored_scope_helper_accepts_string_or_list():
    assert auth._stored_oauth_scopes({"scope": "a b"}) == {"a", "b"}
    assert auth._stored_oauth_scopes({"scopes": ["a", "b"]}) == {"a", "b"}


def test_corrupt_auth_file_is_ignored(monkeypatch, tmp_path):
    auth_path = tmp_path / "auth.json"
    auth_path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(settings, "AUTH_PATH", auth_path)
    monkeypatch.setattr(auth, "AUTH_PATH", auth_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert auth.load() is None
    assert auth.resolve_anthropic() is None
    assert auth.resolve_openai_codex() is None


def test_trace_redacts_environment_secret_values(monkeypatch, tmp_path):
    secret = "env-secret-token-12345"
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CRYPT_TRACE_PATH", str(trace_path))
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    tracing.emit(
        "auth_test",
        message=f"Authorization: Bearer {secret}",
        nested={"token_text": secret, "content": f"value={secret}"},
    )

    raw = trace_path.read_text(encoding="utf-8")
    assert secret not in raw
    event = json.loads(raw.splitlines()[-1])
    assert event["message"] == "Authorization: [redacted]"
    assert event["nested"]["token_text"] == "[redacted]"
    assert event["nested"]["content"] == "value=[redacted]"
