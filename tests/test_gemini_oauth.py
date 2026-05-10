from __future__ import annotations

import json

from core import gemini_oauth


class _FakeCredentials:
    def to_json(self) -> str:
        return json.dumps({
            "token": "token",
            "refresh_token": "refresh",
        })


class _FakeFlow:
    def __init__(self) -> None:
        self.redirect_uri = ""


class _FakeServer:
    server_port = 43210

    def __init__(self, app) -> None:
        self.app = app
        self.closed = False
        self.timeout = None

    def handle_request(self) -> None:
        self.app.last_request_uri = "http://127.0.0.1:43210/?code=abc&state=xyz"

    def server_close(self) -> None:
        self.closed = True


def test_gemini_login_opens_browser_and_uses_client_project(monkeypatch, tmp_path):
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text(
        json.dumps({
            "installed": {
                "project_id": "client-project",
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
        }),
        encoding="utf-8",
    )
    fake_flow = _FakeFlow()

    import google_auth_oauthlib.flow

    monkeypatch.setenv("GEMINI_CLIENT_SECRET_FILE", str(client_secret))
    monkeypatch.delenv("GEMINI_PROJECT_ID", raising=False)
    monkeypatch.setattr(gemini_oauth, "APP_DIR", tmp_path)
    monkeypatch.setattr(gemini_oauth, "restrict_file_permissions", lambda path: None)
    monkeypatch.setattr(
        google_auth_oauthlib.flow.InstalledAppFlow,
        "from_client_secrets_file",
        staticmethod(lambda path, scopes: fake_flow),
    )
    monkeypatch.setattr(gemini_oauth, "_run_oauth_local_server", lambda flow, on_status=None: _FakeCredentials())

    result = gemini_oauth.login()

    assert result["project_id"] == "client-project"
    assert result["credentials"]["project_id"] == "client-project"
    assert result["credentials"]["scopes"] == list(gemini_oauth.GEMINI_OAUTH_SCOPES)
    saved = json.loads((tmp_path / "gemini_token.json").read_text(encoding="utf-8"))
    assert saved["project_id"] == "client-project"


def test_oauth_local_server_prints_url_when_browser_open_fails(monkeypatch):
    events: list[str] = []
    made_servers: list[_FakeServer] = []

    class Flow:
        credentials = _FakeCredentials()

        def __init__(self) -> None:
            self.redirect_uri = ""
            self.auth_kwargs = {}
            self.authorization_response = ""

        def authorization_url(self, **kwargs):
            self.auth_kwargs = kwargs
            return ("https://accounts.google.test/oauth?state=abc", "abc")

        def fetch_token(self, *, authorization_response):
            self.authorization_response = authorization_response

    flow = Flow()

    def fake_make_server(host, port, app, handler_class):
        server = _FakeServer(app)
        made_servers.append(server)
        return server

    monkeypatch.setattr(gemini_oauth.webbrowser, "open", lambda *args, **kwargs: False)
    monkeypatch.setattr(gemini_oauth.wsgiref.simple_server, "make_server", fake_make_server)

    creds = gemini_oauth._run_oauth_local_server(flow, on_status=events.append)

    assert creds is flow.credentials
    assert flow.redirect_uri == "http://127.0.0.1:43210/"
    assert flow.auth_kwargs == {"prompt": "consent", "access_type": "offline"}
    assert flow.authorization_response == "http://127.0.0.1:43210/?code=abc&state=xyz"
    assert made_servers[0].timeout == 600
    assert made_servers[0].closed is True
    assert any("browser did not open automatically" in event for event in events)
    assert "https://accounts.google.test/oauth?state=abc" in events
