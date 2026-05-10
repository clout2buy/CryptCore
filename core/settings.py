"""Small shared settings layer for crypt.

This is intentionally boring: one place for defaults, OAuth constants,
saved preferences, and workspace resolution. Runtime code should import
from here instead of copying constants across modules.
"""
from __future__ import annotations

import json
import os
import subprocess
import getpass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


APP_DIR = Path.home() / ".crypt"
AUTH_PATH = APP_DIR / "auth.json"
CONFIG_PATH = APP_DIR / "config.json"

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"
PROVIDER_OPENAI_CODEX = "openai-codex"
PROVIDER_GEMINI = "gemini"
PROVIDERS = (
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_OPENAI_CODEX,
    PROVIDER_GEMINI,
    PROVIDER_OLLAMA,
)

ANTHROPIC_MODEL = "claude-opus-4-7"
# Anthropic counts the full requested max_tokens against per-minute rate
# limits BEFORE the response is generated, so reserving more is not free.
# 8k is roughly 2x the p99 of real coding-agent responses; turns that need
# more get one auto-retry at ESCALATED_MAX_TOKENS instead of paying the
# rate-limit tax on every single request. Mirrors Claude Code's
# CAPPED_DEFAULT_MAX_TOKENS / ESCALATED_MAX_TOKENS pattern.
ANTHROPIC_MAX_TOKENS = 8_000
ANTHROPIC_ESCALATED_MAX_TOKENS = 32_000
# Anthropic requires `thinking.budget_tokens >= 1024` when thinking is enabled
# AND `budget_tokens < max_tokens`. 4k leaves ~4k for the response itself
# under the default cap, which fits the median real reply.
ANTHROPIC_THINKING_BUDGET = 4_000
ANTHROPIC_MODELS = (
    "claude-opus-4-7",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
)

OPENAI_MODEL = "gpt-5"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MAX_TOKENS = 8_000
OPENAI_MODELS = (
    "gpt-5",
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "o3",
    "o3-mini",
)
OPENAI_CODEX_MODEL = "gpt-5-codex"
OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api"
OPENAI_CODEX_MAX_TOKENS = 32_000
OPENAI_CODEX_MODELS = (
    "gpt-5-codex",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2",
    "codex-mini-latest",
)

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_VERTEX_LOCATION = "us-central1"
GEMINI_MAX_TOKENS = 16_384
GEMINI_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
)
GEMINI_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/generative-language",
)

OLLAMA_MODEL = "gpt-oss:20b"
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_LOCAL_MODELS = (
    "gpt-oss:20b",
    "gpt-oss:120b",
    "qwen2.5-coder:7b",
    "qwen2.5-coder:14b",
    "qwen2.5-coder:32b",
    "deepseek-coder-v2:16b",
)
OLLAMA_CLOUD_MODELS = (
    "kimi-k2.6:cloud",
    "glm-5.1:cloud",
    "deepseek-v4-flash:cloud",
    "deepseek-v4-pro:cloud",
    "gpt-oss:20b-cloud",
    "gpt-oss:120b-cloud",
    "qwen3-coder:30b-cloud",
    "qwen3-coder:480b-cloud",
    "gemma4:4b-cloud",
    "gemma4:12b-cloud",
    "gemma4:27b-cloud",
    "qwen3-vl:2b-cloud",
    "qwen3-vl:32b-cloud",
    "qwen3-vl:235b-cloud",
    "qwen3-coder-next:cloud",
    "minimax-m2.7:cloud",
    "nemotron-3-super:cloud",
    "ministral-3:3b-cloud",
    "ministral-3:8b-cloud",
    "ministral-3:14b-cloud",
    "devstral-small-2:cloud",
    "glm-5:32b-cloud",
    "glm-5:106b-cloud",
    "minimax-m2.5:cloud",
    "qwen3-next:80b-cloud",
    "rnj-1:14b-cloud",
    "rnj-1:32b-cloud",
    "nemotron-3-nano:cloud",
    "kimi-k2.5:cloud",
    "gemini-3-flash-preview:cloud",
    "glm-4.7:cloud",
    "deepseek-v3.2:cloud",
    "kimi-k2:cloud",
    "deepseek-v3.1:cloud",
    "glm-4.6:cloud",
    "llama3.3:70b-cloud",
)
OLLAMA_MODELS = OLLAMA_LOCAL_MODELS + OLLAMA_CLOUD_MODELS

CRYPT_VERSION = "0.3.0"
CRYPT_IDENTITY = "You are Crypt, a local-first software engineering agent."
# Anthropic's OAuth tokens are issued to Claude Code's app id; the edge
# rate-limits OAuth traffic that doesn't present these exact headers
# (429 with no anthropic-ratelimit-* headers). Bump version with the real CLI.
ANTHROPIC_OAUTH_USER_AGENT = "claude-cli/2.1.75"
ANTHROPIC_OAUTH_X_APP = "cli"
ANTHROPIC_BASE_BETAS = (
    "fine-grained-tool-streaming-2025-05-14,"
    "interleaved-thinking-2025-05-14"
)
ANTHROPIC_OAUTH_BETAS = (
    f"claude-code-20250219,oauth-2025-04-20,{ANTHROPIC_BASE_BETAS}"
)

OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
OAUTH_CALLBACK_PORT = 53692
OAUTH_CALLBACK_PATH = "/callback"
OAUTH_REDIRECT_URI = f"http://localhost:{OAUTH_CALLBACK_PORT}{OAUTH_CALLBACK_PATH}"
OAUTH_SCOPES = (
    "org:create_api_key user:profile user:inference "
    "user:sessions:claude_code user:mcp_servers user:file_upload"
)
OAUTH_TIMEOUT = 300


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
    restrict_file_permissions(CONFIG_PATH)


def update_config(**values: object) -> dict:
    data = load_config()
    data.update({k: v for k, v in values.items() if v is not None})
    save_config(data)
    return data


def env(name: str, default: str) -> str:
    return os.getenv(name) or default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def provider_default(saved: dict | None = None) -> str:
    saved = load_config() if saved is None else saved
    explicit = os.getenv("CRYPT_PROVIDER")
    if explicit in PROVIDERS:
        return explicit
    saved_provider = saved.get("provider")
    if saved_provider in PROVIDERS:
        return saved_provider
    if os.getenv("OLLAMA_API_KEY") or os.getenv("OLLAMA_HOST"):
        return PROVIDER_OLLAMA
    if os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_BASE_URL"):
        return PROVIDER_OPENAI
    if os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_PROJECT_ID"):
        return PROVIDER_GEMINI
    if os.getenv("ANTHROPIC_API_KEY"):
        return PROVIDER_ANTHROPIC
    return PROVIDER_OLLAMA


def model_default(provider: str, saved: dict | None = None) -> str:
    saved = load_config() if saved is None else saved
    if provider == PROVIDER_ANTHROPIC:
        return os.getenv("ANTHROPIC_MODEL") or saved.get("anthropic_model") or ANTHROPIC_MODEL
    if provider == PROVIDER_OPENAI:
        return os.getenv("OPENAI_MODEL") or saved.get("openai_model") or OPENAI_MODEL
    if provider == PROVIDER_OPENAI_CODEX:
        return os.getenv("OPENAI_CODEX_MODEL") or saved.get("openai_codex_model") or OPENAI_CODEX_MODEL
    if provider == PROVIDER_GEMINI:
        return os.getenv("GEMINI_MODEL") or saved.get("gemini_model") or GEMINI_MODEL
    explicit = os.getenv("OLLAMA_MODEL")
    if explicit:
        return explicit
    value = saved.get("ollama_model") or OLLAMA_MODEL
    return value


def openai_base_url(saved: dict | None = None) -> str:
    """Returns the configured OpenAI base URL (env > saved > default).
    Lets users point at OpenAI-compatible endpoints (Together, Fireworks,
    LM Studio, vLLM, etc.) without code changes."""
    saved = load_config() if saved is None else saved
    return os.getenv("OPENAI_BASE_URL") or saved.get("openai_base_url") or OPENAI_BASE_URL


def openai_codex_base_url(saved: dict | None = None) -> str:
    """Returns the ChatGPT/Codex backend base URL (env > saved > default)."""
    saved = load_config() if saved is None else saved
    return (
        os.getenv("OPENAI_CODEX_BASE_URL")
        or saved.get("openai_codex_base_url")
        or OPENAI_CODEX_BASE_URL
    )


def gemini_base_url(saved: dict | None = None) -> str:
    """Returns the Gemini API base URL (env > saved > default)."""
    saved = load_config() if saved is None else saved
    return os.getenv("GEMINI_BASE_URL") or saved.get("gemini_base_url") or GEMINI_BASE_URL


def gemini_project_id(saved: dict | None = None) -> str:
    """Returns the Google Cloud project used for OAuth quota routing."""
    saved = load_config() if saved is None else saved
    return os.getenv("GEMINI_PROJECT_ID") or saved.get("gemini_project_id") or ""


def gemini_vertex_location(saved: dict | None = None) -> str:
    """Returns the Vertex AI location for Gemini OAuth requests."""
    saved = load_config() if saved is None else saved
    return os.getenv("GEMINI_LOCATION") or saved.get("gemini_location") or GEMINI_VERTEX_LOCATION


def ollama_host(cli_host: str | None = None, saved: dict | None = None) -> str:
    saved = load_config() if saved is None else saved
    explicit = cli_host or os.getenv("OLLAMA_HOST")
    if explicit:
        return client_host(explicit)
    saved_host = saved.get("ollama_host")
    if saved_host:
        host = client_host(str(saved_host))
        if not (is_ollama_cloud_host(host) and not os.getenv("OLLAMA_API_KEY")):
            return host
    if os.getenv("OLLAMA_API_KEY"):
        return "https://ollama.com"
    return OLLAMA_HOST


def is_ollama_cloud_host(host: str) -> bool:
    parts = urlsplit(client_host(host))
    hostname = (parts.hostname or "").lower()
    return hostname == "ollama.com" or hostname.endswith(".ollama.com")


def is_local_host(host: str) -> bool:
    parts = urlsplit(client_host(host))
    hostname = (parts.hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}


def is_ollama_cloud_model(model: str) -> bool:
    return model.endswith(":cloud") or model.endswith("-cloud")


def ollama_models_for_host(host: str) -> tuple[str, ...]:
    return OLLAMA_CLOUD_MODELS if is_ollama_cloud_host(host) else OLLAMA_LOCAL_MODELS


def ollama_host_for_model(model: str, host: str | None = None) -> str:
    return client_host(host or OLLAMA_HOST)


def client_host(host: str) -> str:
    host = host.strip()
    has_scheme = "://" in host
    raw = host if has_scheme else f"http://{host}"
    parts = urlsplit(raw)
    scheme = parts.scheme or "http"
    hostname = (parts.hostname or "").lower()
    if not has_scheme and (hostname == "ollama.com" or hostname.endswith(".ollama.com")):
        scheme = "https"
    if parts.hostname in {"0.0.0.0", "::", "[::]"}:
        port = parts.port or 11434
        return urlunsplit((scheme, f"127.0.0.1:{port}", "", "", ""))
    if parts.port is None and parts.hostname in {"localhost", "127.0.0.1", "::1"}:
        netloc = f"{parts.hostname}:11434"
        return urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def resolve_workspace(cli_root: str | None = None, saved: dict | None = None) -> Path:
    saved = load_config() if saved is None else saved
    explicit = cli_root or os.getenv("CRYPT_ROOT")
    if explicit:
        return _valid_workspace(Path(explicit))

    saved_root = saved.get("workspace")
    if saved_root:
        saved_path = Path(str(saved_root)).expanduser()
        if saved_path.exists() and saved_path.is_dir():
            return saved_path.resolve()

    cwd = Path.cwd().resolve()
    if not _is_bad_launch_cwd(cwd):
        return cwd

    home = Path.home().resolve()
    return home if home.exists() else cwd


def _valid_workspace(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"workspace does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"workspace is not a directory: {path}")
    return path


def _is_bad_launch_cwd(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    text = str(path).lower()
    return (
        "windows" in parts and "system32" in parts
    ) or "\\program files\\windowsapps" in text


def restrict_file_permissions(path: Path) -> bool:
    """Best-effort owner-only permissions for sensitive Crypt files."""
    try:
        if os.name != "nt":
            os.chmod(path, 0o600)
            return True
        user = _windows_user()
        result = subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{user}:F",
                "SYSTEM:F",
                "Administrators:F",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _windows_user() -> str:
    user = getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    if domain and "\\" not in user:
        return f"{domain}\\{user}"
    return user
