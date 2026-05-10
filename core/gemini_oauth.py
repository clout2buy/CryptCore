"""Google OAuth helper for Gemini API credentials."""
from __future__ import annotations

import json
import os
import webbrowser
import wsgiref.simple_server
from pathlib import Path

from .settings import APP_DIR, GEMINI_OAUTH_SCOPES, restrict_file_permissions


def client_secret_path() -> Path:
    explicit = os.getenv("GEMINI_CLIENT_SECRET_FILE")
    candidates = [
        Path(explicit).expanduser() if explicit else None,
        APP_DIR / "gemini_client_secret.json",
        Path.cwd() / "client_secret.json",
    ]
    for item in candidates:
        if item and item.exists():
            return item.resolve()
    return APP_DIR / "gemini_client_secret.json"


def _client_secret_project_id(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    for key in ("installed", "web"):
        section = data.get(key)
        if isinstance(section, dict) and section.get("project_id"):
            return str(section["project_id"])
    return str(data.get("project_id") or "")


def _run_oauth_local_server(flow, *, on_status=None):
    from google_auth_oauthlib.flow import WSGITimeoutError, _RedirectWSGIApp, _WSGIRequestHandler

    wsgi_app = _RedirectWSGIApp("The authentication flow has completed. You may close this window.")
    wsgiref.simple_server.WSGIServer.allow_reuse_address = False
    local_server = wsgiref.simple_server.make_server(
        "127.0.0.1",
        0,
        wsgi_app,
        handler_class=_WSGIRequestHandler,
    )
    try:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        flow.redirect_uri = f"http://127.0.0.1:{local_server.server_port}/"
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

        opened = False
        try:
            opened = webbrowser.open(auth_url, new=1, autoraise=True)
        except Exception as exc:
            if on_status:
                on_status(f"browser open failed: {exc}")
        if on_status:
            if opened:
                on_status("opened browser for Google OAuth")
            else:
                on_status("browser did not open automatically; open this URL:")
                on_status(auth_url)

        local_server.timeout = 600
        if on_status:
            on_status(f"waiting for callback on {flow.redirect_uri} (timeout 10m)...")
        local_server.handle_request()
        try:
            authorization_response = wsgi_app.last_request_uri
        except AttributeError as exc:
            raise WSGITimeoutError("Timed out waiting for Google OAuth browser callback") from exc
        if not authorization_response:
            raise WSGITimeoutError("Timed out waiting for Google OAuth browser callback")

        if on_status:
            on_status("callback received, fetching tokens...")
        flow.fetch_token(authorization_response=authorization_response)
        if on_status:
            on_status("tokens fetched successfully")
    finally:
        local_server.server_close()
    return flow.credentials


def login(on_status=None) -> dict:
    """Run Google's desktop OAuth flow and return serializable credentials."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception as exc:  # pragma: no cover - exercised in CLI smoke only
        raise RuntimeError(
            "Gemini OAuth requires google-auth-oauthlib. "
            "Install dependencies with `python -m pip install -e .[dev]`."
        ) from exc

    path = client_secret_path()
    if not path.exists():
        raise FileNotFoundError(
            "Gemini OAuth needs a Google desktop OAuth client secret JSON. "
            f"Set GEMINI_CLIENT_SECRET_FILE or place it at {path}."
        )
    if on_status:
        on_status(f"opening Google OAuth flow using {path}")
    flow = InstalledAppFlow.from_client_secrets_file(str(path), scopes=list(GEMINI_OAUTH_SCOPES))
    creds = _run_oauth_local_server(flow, on_status=on_status)
    data = json.loads(creds.to_json())
    data["scopes"] = list(GEMINI_OAUTH_SCOPES)
    project_id = os.getenv("GEMINI_PROJECT_ID") or _client_secret_project_id(path) or data.get("quota_project_id") or ""
    if project_id:
        data["project_id"] = project_id
    token_path = APP_DIR / "gemini_token.json"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    restrict_file_permissions(token_path)
    return {
        "credentials": data,
        "project_id": project_id,
    }
