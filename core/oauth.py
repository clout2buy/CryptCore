"""OAuth PKCE login flow for Anthropic accounts."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen

from .settings import (
    ANTHROPIC_OAUTH_USER_AGENT,
    OAUTH_AUTHORIZE_URL,
    OAUTH_CALLBACK_PATH,
    OAUTH_CALLBACK_PORT,
    OAUTH_CLIENT_ID,
    OAUTH_REDIRECT_URI,
    OAUTH_SCOPES,
    OAUTH_TIMEOUT,
    OAUTH_TOKEN_URL,
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != OAUTH_CALLBACK_PATH:
            self.send_error(404)
            return

        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        if code and state == self.server._expected_state:
            self.server._result = code
            self._respond(200, "Logged in to crypt. You can close this tab.")
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


def _exchange_code(code: str, verifier: str) -> dict:
    body = json.dumps({
        "grant_type": "authorization_code",
        "client_id": OAUTH_CLIENT_ID,
        "code": code,
        "state": verifier,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "code_verifier": verifier,
    }).encode()
    req = Request(OAUTH_TOKEN_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": ANTHROPIC_OAUTH_USER_AGENT,
    })
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def refresh(refresh_token: str) -> dict:
    body = json.dumps({
        "grant_type": "refresh_token",
        "client_id": OAUTH_CLIENT_ID,
        "refresh_token": refresh_token,
    }).encode()
    req = Request(OAUTH_TOKEN_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": ANTHROPIC_OAUTH_USER_AGENT,
    })
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def login(on_status: Callable[[str], None] | None = None) -> dict:
    """Run full PKCE OAuth flow. Returns dict with access_token, refresh_token, expires_in."""
    verifier, challenge = _generate_pkce()

    server = HTTPServer(("127.0.0.1", OAUTH_CALLBACK_PORT), _CallbackHandler)
    server._expected_state = verifier
    server._result = None
    server._done = threading.Event()

    params = urlencode({
        "code": "true",
        "client_id": OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": OAUTH_REDIRECT_URI,
        "scope": OAUTH_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": verifier,
    })
    auth_url = f"{OAUTH_AUTHORIZE_URL}?{params}"

    if on_status:
        on_status("opening browser for login...")

    webbrowser.open(auth_url, new=1, autoraise=True)

    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()

    if not server._done.wait(timeout=OAUTH_TIMEOUT):
        server.server_close()
        raise TimeoutError("login timed out (5 minutes)")

    server.server_close()
    code = server._result
    if not code:
        raise RuntimeError("no authorization code received")

    if on_status:
        on_status("exchanging token...")

    return _exchange_code(code, verifier)
