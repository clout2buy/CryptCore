# Reference

This page keeps operational detail out of the README while preserving the facts
needed to run, fork, and debug Crypt.

## Providers

| Provider | Typical setup | Notes |
|---|---|---|
| Ollama | `ollama serve` then `python -m crypt` | Default for fresh clones. Uses `http://localhost:11434`. |
| Anthropic | `python -m crypt login` or `ANTHROPIC_API_KEY` | OAuth tokens live in `~/.crypt/auth.json`. |
| OpenAI-compatible | `OPENAI_API_KEY=...` | Supports OpenAI Chat Completions-compatible servers. |
| Crypt OAuth | `python -m crypt login --provider crypt` | Uses Crypt subscription OAuth, separate from Platform API keys. |
| Gemini | `GEMINI_API_KEY=...` or `python -m crypt login --provider gemini` | API keys use Gemini Developer API. OAuth uses Vertex AI and needs `GEMINI_PROJECT_ID`. |

## Approval Modes

| Mode | Select with | Behavior |
|---|---|---|
| Manual | `/safe` or `CRYPT_APPROVAL=normal` | Prompt before shell commands and edits |
| Auto-work | default or `CRYPT_APPROVAL=edits` | File edits, ordinary shell/background commands, web search/fetch, and file opens can run; destructive shell still asks |
| YOLO-all | `/yolo all` or `CRYPT_APPROVAL=all` | Bypass normal prompts; danger checks still apply |

Dangerous commands such as `rm -rf`, `git reset --hard`, `git clean`, and
`git push --force` remain approval-gated even when an allow rule matches.

`~/.crypt/permissions.json` also supports shell prefix rules:

```json
{
  "prefix_rules": [
    {"pattern": ["git", "status"], "decision": "allow"},
    {"pattern": ["npm", "install"], "decision": "prompt"},
    {"pattern": ["git", "push", "--force"], "decision": "forbidden"}
  ]
}
```

Decisions are `allow`, `prompt`, or `forbidden`; list entries inside a pattern
act as alternatives.

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

When installed with `scripts\install_crypt.ps1` or `pip install -e .`, the
`crypt` console command uses the current shell directory as the workspace by
default. Saved setup workspace is only a fallback for bad launch locations such
as `System32`; `--cwd` and `CRYPT_ROOT` remain explicit overrides.

## Slash Commands

| Command | Effect |
|---|---|
| `/sessions [--all]` | List resumable sessions |
| `/resume [id\|text]` | Resume a prior session |
| `/compact` | Summarize old context into a continuation snapshot |
| `/memory` | Read durable memory |
| `/memory add <text>` | Save durable memory |
| `/learn` | List learned project lessons |
| `/learn search <text>` | Search learned lessons and prior task episodes |
| `/learn add <text>` | Save an explicit structured lesson |
| `/autonomy [run]` | Inspect or run safe autonomous learning |
| `/skills` | List local `SKILL.md` bundles visible to the workspace |
| `/tasks [id\|--all]` | List or inspect durable task event logs |
| `/project [--refresh]` | Show the project intelligence cache |
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
| Planning | `present_plan`, `todos`, `ask_user`, `memory`, `learn`, `goals`, `reflect`, `autonomy` |
| Learning | `skill_forge` |
| Agents | `spawn_agent`, `list_agents`, `agent_output`, `send_agent_message`, `stop_agent`, `cleanup_agent` |
| Connectors | `mcp` |
| Workspace | `set_workspace`, `open_file` |

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `CRYPT_ROOT` | current cwd | Explicit workspace root override |
| `CRYPT_PROVIDER` | saved setup or `ollama` | `anthropic`, `openai`, `crypt`, `gemini`, or `ollama` |
| `CRYPT_APPROVAL` | `edits` | `normal`, `edits`, or `all` |
| `CRYPT_LEARNING_DISABLE` | unset | Disable learned-context retrieval in prompts |
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
| `CRYPT_MODEL` | provider default | Crypt OAuth model |
| `CRYPT_BASE_URL` | Crypt backend | Crypt backend base URL |
| `CRYPT_MAX_TOKENS` | `32000` | Crypt OAuth output cap |
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

## Skills

Crypt discovers local skills from these roots:

- `<workspace>/.crypt/skills/*/SKILL.md`
- `<workspace>/.agents/skills/*/SKILL.md`
- `~/.crypt/skills/*/SKILL.md`
- `~/.agents/skills/*/SKILL.md`
- `~/.codex/skills/*/SKILL.md`
- `~/.config/agents/skills/*/SKILL.md`

Invoke a skill in a prompt with `$skill-name`. The active skill body is injected
for that turn, while the system prompt lists available skill names. Env-var-like
all-caps mentions such as `$PATH` are ignored, and skills that contain obvious
prompt-injection or secret-exfiltration language are blocked from injection.

Manage skills from the terminal:

```powershell
python main.py skills list
python main.py skills add .\local-skills
python main.py skills add vercel-labs/agent-skills --skill frontend-design -y
python main.py skills remove frontend-design
```

Remote sources are delegated to the upstream `npx skills add` CLI with the
Codex agent target. Local sources are copied into `.agents/skills` by default
or `~/.crypt/skills` with `--global`, and a small lock file records source and
content hash.

## Tasks And Project Intelligence

Every user prompt creates an append-only JSONL task log under the workspace's
`~/.crypt/projects/<project>/tasks/` directory. Statuses include `planning`,
`tool_calling`, `waiting_approval`, `editing`, `verifying`, `completed`,
`failed`, and `cancelled`. Inspect them with:

```powershell
python main.py tasks list
python main.py tasks show <task_id>
```

Completed and failed turns are also summarized into a structured learning store
under `~/.crypt/learning/`. Completed turns derive reusable lessons from runtime
evidence such as passing verification commands, recently changed paths, and
tool recovery hints. Relevant lessons and prior episodes are retrieved into the
next system prompt. Inspect or curate the store with:

```powershell
python main.py learn list
python main.py learn search "parser pytest"
python main.py learn add "For release work, run scripts\verify_core.ps1 -Quick."
python main.py learn episodes
```

Reflection and autonomy build on that store:

```powershell
python main.py reflect run
python main.py autonomy run
python main.py goals add "Launch Crypt assistant" --success "first paying user" --cadence daily
python main.py forge release --min-lessons 2
```

The autonomous cycle is deliberately safe. It teaches, reviews, remembers, and
forges local skills. It does not spend money, send messages, or mutate external
systems without going through normal tool permissions.

Start the local browser cockpit with:

```powershell
python main.py webui --open
```

The browser view is intentionally chat-first. There are no prompt recipes or
route controls to manage. Goals, lessons, reflection, autonomy cycles, and
skill forging stay in the background unless Crypt needs permission or the user
opens the activity drawer.

Crypt also maintains a project profile cache with languages, package managers,
frameworks/libraries, entry points, CI files, likely test/build commands,
instruction files, visible skills, git state, and attention flags. It is
included in the system prompt and can be refreshed manually:

```powershell
python main.py project --refresh
python main.py project --json
```

## MCP Servers

Configure stdio MCP servers in `~/.crypt/config.json`:

```json
{
  "mcp_servers": {
    "demo": {
      "command": "python",
      "args": ["server.py"],
      "framing": "headers"
    }
  }
}
```

Use the `mcp` tool with `action=servers`, `action=tools`, or `action=call`.
Calls start the configured server as a one-shot subprocess and require normal
tool approval. MCP subprocesses receive only a small OS/PATH environment by
default; put required server tokens in that server's explicit `env` block.

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
  learning/            structured task episodes and reusable lessons
  autonomy/            self-review cycle logs
  goals/               durable objectives
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
