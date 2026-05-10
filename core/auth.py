"""Credential storage and resolution."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .settings import AUTH_PATH, restrict_file_permissions


@dataclass
class Credential:
    kind: str
    token: str
    email: str | None = None
    plan: str | None = None
    account_id: str | None = None
    project_id: str | None = None


def _auth_path() -> Path:
    return AUTH_PATH


def load() -> dict | None:
    path = _auth_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save(data: dict) -> None:
    path = _auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
    restrict_file_permissions(path)


def delete() -> None:
    path = _auth_path()
    if path.exists():
        path.unlink()


def save_provider(provider: str, data: dict) -> None:
    """Persist a provider-specific auth record without clobbering others."""
    existing = load() or {}
    records = _as_provider_records(existing)
    records[provider] = data
    save(records)


def load_provider(provider: str) -> dict | None:
    data = load()
    if not data:
        return None
    records = _as_provider_records(data)
    record = records.get(provider)
    return record if isinstance(record, dict) else None


def delete_provider(provider: str) -> None:
    data = load()
    if not data:
        return
    records = _as_provider_records(data)
    records.pop(provider, None)
    if records:
        save(records)
    else:
        delete()


def resolve() -> Credential | None:
    """Backward-compatible Anthropic credential resolver."""
    return resolve_anthropic()


def resolve_anthropic() -> Credential | None:
    """Resolve the best Anthropic credential. OAuth first, then env var."""
    stored = load_provider("anthropic")
    if stored and stored.get("type") in {"oauth", "anthropic_oauth"}:
        access = stored.get("access")
        refresh_tok = stored.get("refresh")
        expires = stored.get("expires", 0)

        now_ms = int(time.time() * 1000)
        if now_ms >= expires and refresh_tok:
            try:
                from .oauth import refresh
                tokens = refresh(refresh_tok)
                access = tokens["access_token"]
                new_refresh = tokens.get("refresh_token", refresh_tok)
                expires_in = tokens.get("expires_in", 3600)
                save_provider("anthropic", {
                    "type": "oauth",
                    "access": access,
                    "refresh": new_refresh,
                    "expires": now_ms + expires_in * 1000 - 5 * 60 * 1000,
                    "email": stored.get("email"),
                    "plan": stored.get("plan"),
                })
            except Exception:
                return None

        if access:
            return Credential(
                kind="oauth",
                token=access,
                email=stored.get("email"),
                plan=stored.get("plan"),
            )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        kind = "oauth" if api_key.startswith("sk-ant-oat") else "api"
        return Credential(kind=kind, token=api_key)

    return None


def resolve_openai_codex() -> Credential | None:
    """Resolve ChatGPT OAuth credentials for the OpenAI Codex backend."""
    stored = load_provider("openai-codex")
    if not stored or stored.get("type") != "openai-codex":
        return None

    access = stored.get("access")
    refresh_tok = stored.get("refresh")
    expires = stored.get("expires", 0)
    now_ms = int(time.time() * 1000)

    if now_ms >= expires and refresh_tok:
        try:
            from .openai_oauth import refresh

            tokens = refresh(refresh_tok)
            access = tokens["access_token"]
            new_refresh = tokens.get("refresh_token", refresh_tok)
            expires_in = tokens.get("expires_in", 3600)
            claims = tokens.get("claims") or {}
            stored = {
                "type": "openai-codex",
                "access": access,
                "refresh": new_refresh,
                "expires": now_ms + expires_in * 1000 - 5 * 60 * 1000,
                "account_id": tokens.get("account_id") or stored.get("account_id"),
                "email": claims.get("email") or stored.get("email"),
                "plan": tokens.get("plan") or stored.get("plan"),
            }
            save_provider("openai-codex", stored)
        except Exception:
            return None

    if access:
        return Credential(
            kind="oauth",
            token=access,
            email=stored.get("email"),
            plan=stored.get("plan"),
            account_id=stored.get("account_id"),
        )

    return None


def resolve_gemini(*, include_adc: bool = False) -> Credential | None:
    """Resolve Gemini credentials.

    Interactive Crypt startup intentionally does not use ADC by default. ADC can
    be scoped for unrelated Google APIs and caused Gemini to skip browser login
    before failing with ACCESS_TOKEN_SCOPE_INSUFFICIENT. Callers that explicitly
    want ADC, such as doctor diagnostics, can opt in with include_adc=True.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        return Credential(kind="api", token=api_key, project_id=os.getenv("GEMINI_PROJECT_ID"))

    stored = load_provider("gemini")
    if stored and stored.get("type") == "gemini-oauth":
        cred = _resolve_stored_gemini(stored)
        if cred:
            return cred

    if include_adc:
        return _resolve_adc_gemini()
    return None


def _resolve_stored_gemini(stored: dict) -> Credential | None:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        from .settings import GEMINI_OAUTH_SCOPES

        info = stored.get("credentials") if isinstance(stored.get("credentials"), dict) else stored
        required_scopes = set(GEMINI_OAUTH_SCOPES)
        stored_scopes = _stored_oauth_scopes(info)
        if stored_scopes and not required_scopes.issubset(stored_scopes):
            return None
        creds = Credentials.from_authorized_user_info(info, scopes=list(GEMINI_OAUTH_SCOPES))
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                refreshed = json.loads(creds.to_json())
                refreshed["scopes"] = list(GEMINI_OAUTH_SCOPES)
                project_id = stored.get("project_id") or os.getenv("GEMINI_PROJECT_ID")
                if project_id:
                    refreshed["project_id"] = project_id
                save_provider("gemini", {
                    "type": "gemini-oauth",
                    "credentials": refreshed,
                    "project_id": project_id,
                    "email": stored.get("email"),
                })
            else:
                return None
        if creds.token:
            return Credential(
                kind="oauth",
                token=creds.token,
                email=stored.get("email"),
                project_id=stored.get("project_id") or os.getenv("GEMINI_PROJECT_ID"),
            )
    except Exception:
        return None
    return None


def _stored_oauth_scopes(info: dict) -> set[str]:
    raw = info.get("scopes") or info.get("scope")
    if isinstance(raw, str):
        return set(raw.split())
    if isinstance(raw, list):
        return {str(scope) for scope in raw}
    return set()


def _resolve_adc_gemini() -> Credential | None:
    try:
        import google.auth
        from google.auth.transport.requests import Request

        from .settings import GEMINI_OAUTH_SCOPES

        creds, project_id = google.auth.default(scopes=list(GEMINI_OAUTH_SCOPES))
        if not creds.valid:
            creds.refresh(Request())
        token = getattr(creds, "token", "")
        if token:
            return Credential(
                kind="oauth",
                token=token,
                project_id=os.getenv("GEMINI_PROJECT_ID") or project_id,
            )
    except Exception:
        return None
    return None


def _as_provider_records(data: dict) -> dict[str, dict]:
    """Normalize legacy single-provider auth.json into provider records."""
    if any(k in data for k in ("anthropic", "openai-codex", "gemini")):
        return {
            k: v
            for k, v in data.items()
            if isinstance(v, dict)
        }

    if data.get("type") in {"oauth", "anthropic_oauth"}:
        return {"anthropic": data}
    if data.get("type") == "openai-codex":
        return {"openai-codex": data}
    return {}
