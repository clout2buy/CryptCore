from __future__ import annotations

import argparse

import main
from core import settings
from core.doctor import _check_provider_auth


def _clear_provider_env(monkeypatch) -> None:
    for name in (
        "CRYPT_PROVIDER",
        "CRYPT_REQUIRE_SETUP",
        "CRYPT_PICKER",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_CODEX_BASE_URL",
        "OPENAI_CODEX_MODEL",
        "GEMINI_API_KEY",
        "GEMINI_BASE_URL",
        "GEMINI_CLIENT_SECRET_FILE",
        "GEMINI_LOCATION",
        "GEMINI_MODEL",
        "GEMINI_PROJECT_ID",
        "OLLAMA_API_KEY",
        "OLLAMA_HOST",
    ):
        monkeypatch.delenv(name, raising=False)


def _args(**overrides):
    values = {
        "provider": None,
        "model": None,
        "cwd": None,
        "ollama_host": None,
        "no_picker": False,
        "no_thinking": False,
        "show_thinking": False,
        "max_tokens": None,
        "thinking_budget": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_fresh_clone_defaults_to_ollama_without_setup(monkeypatch):
    _clear_provider_env(monkeypatch)

    assert settings.provider_default({}) == settings.PROVIDER_OLLAMA
    assert settings.ollama_host(saved={}) == "http://localhost:11434"
    assert settings.model_default(settings.PROVIDER_OLLAMA, {}) == "gpt-oss:20b"
    assert main._needs_setup({}, _args()) is False


def test_env_and_saved_provider_precedence(monkeypatch):
    _clear_provider_env(monkeypatch)

    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
    assert settings.provider_default({}) == settings.PROVIDER_OLLAMA

    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    assert settings.provider_default({"provider": settings.PROVIDER_ANTHROPIC}) == settings.PROVIDER_ANTHROPIC

    monkeypatch.setenv("CRYPT_PROVIDER", settings.PROVIDER_OPENAI)
    assert settings.provider_default({"provider": settings.PROVIDER_ANTHROPIC}) == settings.PROVIDER_OPENAI

    monkeypatch.setenv("CRYPT_PROVIDER", settings.PROVIDER_OPENAI_CODEX)
    assert settings.provider_default({}) == settings.PROVIDER_OPENAI_CODEX


def test_startup_choice_does_not_prompt_on_first_run(monkeypatch):
    _clear_provider_env(monkeypatch)

    class _Tty:
        def isatty(self):
            return True

    monkeypatch.setattr(main.sys, "stdin", _Tty())

    provider, model = main._startup_choice({}, _args(), skip=False)

    assert provider == settings.PROVIDER_OLLAMA
    assert model is None


def test_ollama_auth_label_distinguishes_cloud_and_local(monkeypatch):
    _clear_provider_env(monkeypatch)

    cloud = main._provider_auth_label(
        settings.PROVIDER_OLLAMA,
        _args(ollama_host="https://ollama.com"),
        {},
        None,
    )
    local = main._provider_auth_label(
        settings.PROVIDER_OLLAMA,
        _args(),
        {"ollama_host": "http://localhost:11434"},
        None,
    )

    assert cloud == "missing OLLAMA_API_KEY"
    assert local == "local Ollama"


def test_ollama_host_normalization_classifies_bare_hosts():
    assert settings.client_host("localhost:11434") == "http://localhost:11434"
    assert settings.client_host("ollama.com") == "https://ollama.com"
    assert settings.is_local_host("localhost:11434") is True
    assert settings.is_ollama_cloud_host("ollama.com") is True


def test_openai_codex_auth_label_uses_chatgpt_oauth(monkeypatch):
    _clear_provider_env(monkeypatch)

    missing = main._provider_auth_label(settings.PROVIDER_OPENAI_CODEX, _args(), {}, None)
    present = main._provider_auth_label(
        settings.PROVIDER_OPENAI_CODEX,
        _args(),
        {},
        main.auth.Credential(kind="oauth", token="token", email="me@example.com"),
    )

    assert missing == "missing ChatGPT OAuth"
    assert present == "ChatGPT OAuth (me@example.com)"


def test_login_if_needed_runs_chatgpt_login_before_provider(monkeypatch):
    _clear_provider_env(monkeypatch)
    calls: list[str] = []

    monkeypatch.setattr(main.ui, "ask", lambda prompt: True)
    monkeypatch.setattr(main, "_do_login", lambda provider: calls.append(provider) or 0)
    monkeypatch.setattr(
        main,
        "_credential",
        lambda provider: main.auth.Credential(kind="oauth", token="token", account_id="account-123")
        if calls
        else None,
    )

    cred = main._login_if_needed(settings.PROVIDER_OPENAI_CODEX, None)

    assert calls == [settings.PROVIDER_OPENAI_CODEX]
    assert cred is not None
    assert cred.account_id == "account-123"


def test_login_if_needed_repairs_incomplete_chatgpt_credential(monkeypatch):
    _clear_provider_env(monkeypatch)
    calls: list[str] = []
    incomplete = main.auth.Credential(kind="oauth", token="token")

    monkeypatch.setattr(main.ui, "ask", lambda prompt: "account id is missing" in prompt)
    monkeypatch.setattr(main, "_do_login", lambda provider: calls.append(provider) or 0)
    monkeypatch.setattr(
        main,
        "_credential",
        lambda provider: main.auth.Credential(kind="oauth", token="token-2", account_id="account-456"),
    )

    cred = main._login_if_needed(settings.PROVIDER_OPENAI_CODEX, incomplete)

    assert calls == [settings.PROVIDER_OPENAI_CODEX]
    assert cred is not None
    assert cred.token == "token-2"
    assert cred.account_id == "account-456"


def test_login_if_needed_does_not_prompt_for_openai_api_provider(monkeypatch):
    _clear_provider_env(monkeypatch)

    def fail_if_called(prompt):
        raise AssertionError(f"unexpected prompt: {prompt}")

    monkeypatch.setattr(main.ui, "ask", fail_if_called)

    assert main._login_if_needed(settings.PROVIDER_OPENAI, None) is None


def test_login_if_needed_does_not_prompt_when_non_interactive(monkeypatch):
    _clear_provider_env(monkeypatch)

    def fail_if_called(prompt):
        raise AssertionError(f"unexpected prompt: {prompt}")

    monkeypatch.setattr(main.ui, "ask", fail_if_called)

    assert main._login_if_needed(settings.PROVIDER_OPENAI_CODEX, None, interactive=False) is None


def test_login_if_needed_runs_gemini_login_before_provider(monkeypatch):
    _clear_provider_env(monkeypatch)
    calls: list[str] = []

    monkeypatch.setattr(main.ui, "ask", lambda prompt: "Gemini" in prompt)
    monkeypatch.setattr(main, "_do_login", lambda provider: calls.append(provider) or 0)
    monkeypatch.setattr(
        main,
        "_credential",
        lambda provider: main.auth.Credential(kind="oauth", token="token", project_id="project-123"),
    )

    cred = main._login_if_needed(settings.PROVIDER_GEMINI, None)

    assert calls == [settings.PROVIDER_GEMINI]
    assert cred is not None
    assert cred.project_id == "project-123"


def test_gemini_provider_uses_api_key_from_env(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    provider = main._provider(_args(), {}, settings.PROVIDER_GEMINI)

    assert provider.is_oauth is False
    assert provider._api_key == "gemini-key"
    assert provider._stream_url() == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-2.5-flash:streamGenerateContent?alt=sse"
    )


def test_gemini_provider_uses_vertex_url_for_oauth(monkeypatch):
    _clear_provider_env(monkeypatch)
    cred = main.auth.Credential(kind="oauth", token="token", project_id="project-123")

    provider = main._provider(
        _args(model="models/gemini-2.5-pro"),
        {"gemini_location": "us-central1"},
        settings.PROVIDER_GEMINI,
        cred,
    )

    assert provider.is_oauth is True
    assert provider._stream_url() == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/project-123/locations/us-central1/"
        "publishers/google/models/gemini-2.5-pro:streamGenerateContent?alt=sse"
    )


def test_gemini_oauth_token_without_project_is_usable(monkeypatch):
    _clear_provider_env(monkeypatch)
    cred = main.auth.Credential(kind="oauth", token="token", project_id="")

    assert main._credential_is_usable(settings.PROVIDER_GEMINI, cred) is True


def test_ollama_auth_label_uses_runtime_local_transport_for_cloud_model(monkeypatch):
    _clear_provider_env(monkeypatch)

    provider = main._provider(_args(model="ministral-3:14b-cloud"), {}, settings.PROVIDER_OLLAMA)

    assert main._provider_auth_label(settings.PROVIDER_OLLAMA, _args(), {}, None, provider=provider) == "local Ollama"


def test_saved_cloud_ollama_without_key_uses_local_ollama_transport(monkeypatch):
    _clear_provider_env(monkeypatch)
    saved = {
        "provider": settings.PROVIDER_OLLAMA,
        "ollama_host": "https://ollama.com",
        "ollama_model": "glm-5.1:cloud",
    }

    assert settings.ollama_host(saved=saved) == "http://localhost:11434"
    assert settings.model_default(settings.PROVIDER_OLLAMA, saved) == "glm-5.1:cloud"


def test_saved_cloud_ollama_with_key_stays_cloud(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OLLAMA_API_KEY", "key")
    saved = {
        "provider": settings.PROVIDER_OLLAMA,
        "ollama_host": "https://ollama.com",
        "ollama_model": "glm-5.1:cloud",
    }

    assert settings.ollama_host(saved=saved) == "https://ollama.com"
    assert settings.model_default(settings.PROVIDER_OLLAMA, saved) == "glm-5.1:cloud"


def test_ollama_model_choices_match_host():
    local = settings.ollama_models_for_host("http://localhost:11434")
    cloud = settings.ollama_models_for_host("https://ollama.com")

    assert "gpt-oss:20b" in local
    assert "glm-5.1:cloud" not in local
    assert "glm-5.1:cloud" in cloud
    assert "gpt-oss:20b" not in cloud


def test_openai_codex_model_default_and_choices(monkeypatch):
    _clear_provider_env(monkeypatch)
    seen: list[str] = []

    def fake_pick(label, options, default):
        seen.extend(value for value, _ in options)
        return settings.OPENAI_CODEX_MODEL

    monkeypatch.setattr(main, "_pick", fake_pick)

    assert settings.model_default(settings.PROVIDER_OPENAI_CODEX, {}) == settings.OPENAI_CODEX_MODEL
    assert main._pick_model(settings.PROVIDER_OPENAI_CODEX, {}) == settings.OPENAI_CODEX_MODEL
    assert settings.OPENAI_CODEX_MODEL in seen


def test_ollama_picker_offers_local_and_cloud_models(monkeypatch):
    _clear_provider_env(monkeypatch)
    seen: list[str] = []

    def fake_pick(label, options, default):
        seen.extend(value for value, _ in options)
        return "ministral-3:14b-cloud"

    monkeypatch.setattr(main, "_pick", fake_pick)

    assert main._pick_model(settings.PROVIDER_OLLAMA, {}, host="http://localhost:11434") == "ministral-3:14b-cloud"
    assert "gpt-oss:20b" in seen
    assert "ministral-3:14b-cloud" in seen
    assert "kimi-k2:latest" not in seen


def test_cloud_model_uses_configured_ollama_transport():
    assert settings.ollama_host_for_model("glm-5.1:cloud", "http://localhost:11434") == "http://localhost:11434"
    assert settings.ollama_host_for_model("gpt-oss:20b", "https://ollama.com") == "https://ollama.com"


def test_ollama_provider_does_not_think_unless_thinking_is_shown(monkeypatch):
    _clear_provider_env(monkeypatch)

    provider = main._provider(_args(), {}, settings.PROVIDER_OLLAMA)
    shown_provider = main._provider(_args(show_thinking=True), {}, settings.PROVIDER_OLLAMA)

    assert provider._think is False
    assert shown_provider._think is True


def test_provider_keeps_cloud_model_on_local_ollama_transport(monkeypatch):
    _clear_provider_env(monkeypatch)

    provider = main._provider(_args(model="glm-5.1:cloud"), {}, settings.PROVIDER_OLLAMA)

    assert provider.model == "glm-5.1:cloud"
    assert provider._base_url == "http://localhost:11434"


def test_runtime_choice_saves_cloud_host_for_cloud_model(monkeypatch, tmp_path):
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config.json")

    main._save_runtime_choice(
        _args(),
        {},
        settings.PROVIDER_OLLAMA,
        "ministral-3:14b-cloud",
        tmp_path,
    )

    saved = settings.load_config()
    assert saved["ollama_model"] == "ministral-3:14b-cloud"
    assert saved["ollama_host"] == "http://localhost:11434"


def test_doctor_reports_missing_ollama_cloud_key(monkeypatch, tmp_path):
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("CRYPT_PROVIDER", settings.PROVIDER_OLLAMA)
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.com")

    check = _check_provider_auth()

    assert check.ok is False
    assert "OLLAMA_API_KEY" in check.detail
    assert "Anthropic login is not used for Ollama" in check.detail


def test_doctor_accepts_default_local_ollama_without_key(monkeypatch, tmp_path):
    _clear_provider_env(monkeypatch)
    monkeypatch.setattr(settings, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setenv("CRYPT_PROVIDER", settings.PROVIDER_OLLAMA)

    check = _check_provider_auth()

    assert check.ok is True
    assert "local Ollama" in check.detail
    assert "no key required" in check.detail
