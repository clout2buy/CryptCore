# Reference

This page keeps operational detail out of the README while preserving the facts
needed to run, fork, and debug Crypt.

## Providers

| Provider | Typical setup | Notes |
|---|---|---|
| Ollama | `ollama serve` then `python -m crypt` | Default for fresh clones. Uses `http://localhost:11434`. |
| Anthropic | `python -m crypt login` or `ANTHROPIC_API_KEY` | OAuth tokens live in `~/.crypt/auth.json`. |
| OpenAI-compatible | `OPENAI_API_KEY=...` | Supports OpenAI Chat Completions-compatible servers. |
| ChatGPT/Codex OAuth | `python -m crypt login --provider openai-codex` | Uses ChatGPT/Codex OAuth, separate from Platform API keys. |
| Gemini | `GEMINI_API_KEY=...` or `python -m crypt login --provider gemini` | API keys use Gemini Developer API. OAuth uses Vertex AI and needs `GEMINI_PROJECT_ID`. |

## Approval Modes

| Mode | Select with | Behavior |
|---|---|---|
| Manual | `/safe` or `CRYPT_APPROVAL=normal` | Prompt before shell commands and edits |
| Auto-work | default or `CRYPT_APPROVAL=edits` | File edits, ordinary shell/background commands, web search/fetch, and file opens can run; destructive shell still asks |
| YOLO-all | `/yolo all` or `CRYPT_APPROVAL=all` | Bypass normal prompts; danger checks still apply |

Dangerous commands such as `rm -rf`, `git reset --hard`, `git clean`, and
`git push --force` remain approval-gated.

## Runtime Bridge

CryptCore is terminal-first, but it also exposes a headless JSONL bridge for
trusted clients that want to drive the same runtime from another interface.
Start it with `python -m crypt app-daemon`, send JSON commands on stdin, and
consume structured events from stdout.

| Command | Purpose |
|---|---|
| `python -m crypt app-daemon` | Start the JSONL runtime bridge |
| `python main.py app-daemon --cwd <path>` | Start the bridge against a workspace |

UI clients are outside this repository. They should treat the daemon as an API
over CryptCore, not as a reason to fork terminal behavior.

## Slash Commands

| Command | Effect |
|---|---|
| `/sessions [--all]` | List resumable sessions |
| `/resume [id\|text]` | Resume a prior session |
| `/compact` | Summarize old context into a continuation snapshot |
| `/memory` | Read durable memory |
| `/memory add <text>` | Save durable memory |
| `/background` | List background shell jobs |
| `/doctor` | Run local self-checks |
| `/safe` | Switch to manual approvals |
| `/yolo` | Switch to auto-work approvals |

## Tool Catalog

| Category | Tools |
|---|---|
| Read | `read_file`, `read_media`, `list_files`, `glob`, `grep` |
| Write | `edit_file`, `multi_edit`, `write_file` |
| Shell | `bash`, `bash_start`, `bash_poll`, `bash_kill` |
| Git | `git`, `git_branch`, `git_stage`, `git_commit` |
| Web | `web_search`, `web_fetch` |
| Planning | `present_plan`, `todos`, `ask_user`, `memory` |
| Agents | `spawn_agent`, `list_agents`, `agent_output`, `send_agent_message`, `stop_agent`, `cleanup_agent` |
| Workspace | `set_workspace`, `open_file` |

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `CRYPT_ROOT` | saved setup or cwd | Workspace root |
| `CRYPT_PROVIDER` | saved setup or `ollama` | `anthropic`, `openai`, `openai-codex`, `gemini`, or `ollama` |
| `CRYPT_APPROVAL` | `edits` | `normal`, `edits`, or `all` |
| `CRYPT_REASONING_STALL_SECONDS` | `45` | Abort hidden reasoning-only stalls; `0` disables |
| `CRYPT_NO_ANIMATION` | unset | Disable startup animation |
| `CRYPT_WEB_ALLOW_PRIVATE` | unset | Allow private network `web_fetch` targets |
| `CRYPT_WEB_ALLOWED_HOSTS` | unset | Comma-separated fetch allowlist |
| `CRYPT_WEB_DENIED_HOSTS` | unset | Comma-separated fetch denylist |
| `ANTHROPIC_MODEL` | `claude-opus-4-7` | Default Anthropic model |
| `ANTHROPIC_MAX_TOKENS` | `8000` | Anthropic output cap |
| `ANTHROPIC_THINKING_BUDGET` | `4000` | Anthropic thinking budget |
| `OPENAI_MODEL` | provider default | Default OpenAI-compatible model |
| `OPENAI_BASE_URL` | OpenAI API | Compatible endpoint base URL |
| `OPENAI_MAX_TOKENS` | `8000` | OpenAI-compatible output cap |
| `OPENAI_CODEX_MODEL` | `gpt-5-codex` | ChatGPT/Codex OAuth model |
| `OPENAI_CODEX_BASE_URL` | ChatGPT backend | Codex backend base URL |
| `OPENAI_CODEX_MAX_TOKENS` | `32000` | Codex output cap |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Default Gemini model |
| `GEMINI_API_KEY` | unset | Gemini Developer API key auth |
| `GEMINI_PROJECT_ID` | unset | Google Cloud project for Gemini OAuth through Vertex AI |
| `GEMINI_LOCATION` | `us-central1` | Vertex AI location for Gemini OAuth |
| `GEMINI_CLIENT_SECRET_FILE` | `~/.crypt/gemini_client_secret.json` | Desktop OAuth client JSON for browser login |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | local default | Ollama model |
| `OLLAMA_API_KEY` | `ollama` | Only needed for cloud/custom auth |
| `OLLAMA_MAX_TOKENS` | `16384` | Ollama output cap |
| `OLLAMA_THINKING_BUDGET` | `0` | Ollama reasoning budget |
| `OLLAMA_TIMEOUT` | `600` | Ollama request timeout seconds |

## Project Instructions

Crypt auto-loads project guidance from the workspace and parent directories:

- `CRYPT.md`
- `AGENTS.md`
- `CLAUDE.md`
- `.crypt/instructions.md`

## Files Written Outside The Repo

```text
~/.crypt/
  auth.json            OAuth tokens
  config.json          saved provider, model, and workspace defaults
  permissions.json     optional allow/deny rules
  memory/MEMORY.md     durable memory
  bench-runs/          benchmark workspaces and reports
  target-evals/        target-eval snapshots, traces, reports
  projects/<slug>/     session JSONL transcripts
  runs/                shell output spill files
  tasks/<sid>/         background shell job logs
  worktrees/           isolated subagent worktrees
  traces/              structured traces
```

## Benchmark And Eval Commands

```bash
python -m crypt bench --bench-list
python -m crypt bench --provider openai --model gpt-5-mini --bench-max-tasks 1
python -m crypt bench --bench-suite benchmarks/smoke.json
python -m crypt eval-target --cwd D:\DoingBot --eval-check "python -m pytest tests -q"
```

Benchmark runs use isolated workspaces under `~/.crypt/bench-runs/`. Target evals
run against an existing repo, snapshot the tree, execute checks, clean generated
artifacts, and report suspicious churn.
