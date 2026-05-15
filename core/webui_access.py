"""Access control for optional remote Crypt WebUI sessions."""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import ParseResult


ALL_SCOPES = frozenset({"read", "write", "voice", "backup"})
COOKIE_NAME = "crypt_access"


@dataclass(frozen=True)
class AccessConfig:
    remote: bool
    enabled: bool
    token_hash: str = ""
    scopes: frozenset[str] = ALL_SCOPES

    def to_dict(self) -> dict:
        return {
            "remote": self.remote,
            "enabled": self.enabled,
            "requiresToken": self.enabled,
            "scopes": sorted(self.scopes),
        }


@dataclass(frozen=True)
class AccessDecision:
    ok: bool
    status: HTTPStatus = HTTPStatus.OK
    reason: str = ""
    set_cookie: str = ""


def build(host: str, *, token: str = "", scopes: str | list[str] | None = None) -> AccessConfig:
    remote = _is_remote_host(host)
    raw_token = (token or os.getenv("CRYPT_WEBUI_ACCESS_TOKEN") or "").strip()
    if remote and not raw_token:
        raise ValueError("remote WebUI host requires --access-token or CRYPT_WEBUI_ACCESS_TOKEN")
    enabled = bool(raw_token)
    return AccessConfig(
        remote=remote,
        enabled=enabled,
        token_hash=_hash_token(raw_token) if raw_token else "",
        scopes=_parse_scopes(scopes),
    )


def authorize(config: AccessConfig, *, method: str, parsed: ParseResult, headers) -> AccessDecision:
    scope = scope_for(method, parsed.path)
    if not config.enabled:
        return AccessDecision(True)
    if scope not in config.scopes:
        return AccessDecision(False, HTTPStatus.FORBIDDEN, f"scope required: {scope}")
    token = _token_from_request(parsed, headers)
    if not token or not _matches(config, token):
        return AccessDecision(False, HTTPStatus.UNAUTHORIZED, "valid Crypt access token required")
    set_cookie = ""
    if _token_from_query(parsed) == token:
        set_cookie = _cookie_header(token)
    return AccessDecision(True, set_cookie=set_cookie)


def scope_for(method: str, path: str) -> str:
    verb = method.upper()
    if path == "/api/backup" or path == "/api/backup/restore":
        return "backup"
    if path == "/api/voice" or path.startswith("/api/voice/"):
        return "voice"
    if verb == "GET":
        return "read"
    return "write"


def _token_from_request(parsed: ParseResult, headers) -> str:
    auth = str(headers.get("Authorization") or "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    header_token = str(headers.get("X-Crypt-Access") or "").strip()
    if header_token:
        return header_token
    query_token = _token_from_query(parsed)
    if query_token:
        return query_token
    cookie = SimpleCookie(str(headers.get("Cookie") or ""))
    morsel = cookie.get(COOKIE_NAME)
    return morsel.value.strip() if morsel else ""


def _token_from_query(parsed: ParseResult) -> str:
    query = parsed.query or ""
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        if key in {"token", "access_token"}:
            return value.strip()
    return ""


def _cookie_header(token: str) -> str:
    return f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax"


def _matches(config: AccessConfig, token: str) -> bool:
    if not config.token_hash:
        return False
    return hmac.compare_digest(config.token_hash, _hash_token(token.strip()))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_scopes(value: str | list[str] | None) -> frozenset[str]:
    if value is None or value == "":
        return ALL_SCOPES
    raw = value if isinstance(value, list) else str(value).replace(",", " ").split()
    scopes = {str(item).strip().lower() for item in raw if str(item).strip()}
    unknown = scopes - set(ALL_SCOPES)
    if unknown:
        raise ValueError(f"unknown WebUI access scope: {', '.join(sorted(unknown))}")
    return frozenset(scopes or ALL_SCOPES)


def _is_remote_host(host: str) -> bool:
    value = str(host or "").strip().lower().strip("[]")
    return value not in {"", "127.0.0.1", "localhost", "::1"}
