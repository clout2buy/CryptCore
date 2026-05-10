"""ChatGPT OAuth login flow for OpenAI Codex subscription access."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 1455
CALLBACK_FALLBACK_PORT = 1457
CALLBACK_PATH = "/auth/callback"
SCOPES = "openid profile email offline_access api.connectors.read api.connectors.invoke"
JWT_CLAIM_PATH = "https://api.openai.com/auth"
TIMEOUT_SECONDS = 300


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _decode_jwt_payload(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:
        return {}


def _claims_from_token(token: str) -> dict:
    payload = _decode_jwt_payload(token)
    auth_claims = payload.get(JWT_CLAIM_PATH)
    if not isinstance(auth_claims, dict):
        auth_claims = {}
    claims = dict(auth_claims)
    if payload.get("email"):
        claims["email"] = payload["email"]
    return claims


def _account_id_from_token(token: str) -> str | None:
    account_id = _claims_from_token(token).get("chatgpt_account_id")
    return account_id if isinstance(account_id, str) and account_id else None


def _plan_from_token(token: str) -> str | None:
    plan = _claims_from_token(token).get("chatgpt_plan_type")
    return plan if isinstance(plan, str) and plan else None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return

        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]
        error_description = params.get("error_description", [None])[0]

        if error:
            self.server._error = error_description or error
            self._respond(400, f"OpenAI login failed: {self.server._error}")
        elif code and state == self.server._expected_state:
            self.server._result = code
            self._respond(200, "Logged in to Crypt with ChatGPT. You can close this tab.")
        else:
            self._respond(400, "Login failed - state mismatch or missing code.")

        self.server._done.set()

    def _respond(self, status: int, message: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = f"<html><body><h2>{message}</h2></body></html>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        pass


def _make_server() -> HTTPServer:
    try:
        return HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
    except OSError:
        return HTTPServer((CALLBACK_HOST, CALLBACK_FALLBACK_PORT), _CallbackHandler)


def _redirect_uri(server: HTTPServer) -> str:
    port = int(server.server_address[1])
    return f"http://localhost:{port}{CALLBACK_PATH}"


def _enrich_tokens(tokens: dict) -> dict:
    access = tokens.get("access_token", "")
    id_token = tokens.get("id_token", "")
    claims = _claims_from_token(access) or _claims_from_token(id_token)
    account_id = _account_id_from_token(access) or _account_id_from_token(id_token)
    plan = _plan_from_token(access) or _plan_from_token(id_token)
    enriched = dict(tokens)
    enriched["claims"] = claims
    enriched["account_id"] = account_id
    enriched["plan"] = plan
    return enriched


def _post_form(url: str, form: dict[str, str]) -> dict:
    body = urlencode(form).encode("utf-8")
    req = Request(url, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def exchange_code(code: str, verifier: str, redirect_uri: str) -> dict:
    tokens = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
    })
    return _enrich_tokens(tokens)


def refresh(refresh_token: str) -> dict:
    tokens = _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    })
    return _enrich_tokens(tokens)


def login(on_status: Callable[[str], None] | None = None) -> dict:
    """Run ChatGPT OAuth PKCE flow. Returns access/refresh token metadata."""
    verifier, challenge = _generate_pkce()
    state = _b64url(secrets.token_bytes(32))

    server = _make_server()
    server._expected_state = state
    server._result = None
    server._error = None
    server._done = threading.Event()
    redirect_uri = _redirect_uri(server)

    params = urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": "crypt",
    })
    auth_url = f"{AUTHORIZE_URL}?{params}"

    if on_status:
        on_status("opening browser for ChatGPT login...")
    webbrowser.open(auth_url, new=1, autoraise=True)

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    if not server._done.wait(timeout=TIMEOUT_SECONDS):
        server.server_close()
        raise TimeoutError("login timed out (5 minutes)")

    server.server_close()
    if server._error:
        raise RuntimeError(str(server._error))
    code = server._result
    if not code:
        raise RuntimeError("no authorization code received")

    if on_status:
        on_status("exchanging ChatGPT token...")
    tokens = exchange_code(code, verifier, redirect_uri)
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise RuntimeError("OpenAI token exchange response missing access or refresh token")
    if not tokens.get("account_id"):
        raise RuntimeError("OpenAI token did not include a ChatGPT account id")
    return tokens
