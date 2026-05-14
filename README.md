# CryptCore

CryptCore is the protected Python runtime and terminal coding harness behind
Crypt. It owns the agent loop, provider routing, typed tools, approvals,
sessions, memory, subagents, safety checks, tests, and release gates.

The core runtime now includes durable task event logs, a project intelligence
cache, portable `SKILL.md` discovery/installation, typed subagents, MCP
isolation, structured runtime learning, workspace switching, and
verification/eval commands. Those are the stable kernel surfaces for future
desktop, web, gateway, or messaging shells.

This repository intentionally does not include the Electron desktop app,
renderer, packaged build outputs, or Agent D UI experiments. Those layers can
sit on top of CryptCore, but the terminal harness remains the source of truth.

## What This Is

- A local-first coding agent runtime.
- A terminal-first harness for model/tool execution.
- A Python package with a `crypt` CLI entrypoint.
- A stable base for desktop, web, or assistant shells.

## What This Is Not

- A desktop UI repository.
- An Agent D personality/product shell.
- A place for generated traces, packaged apps, auth tokens, or local caches.

## Run

```powershell
python main.py
```

Install/link the CLI so `crypt` works from any PowerShell directory:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_crypt.ps1
```

After opening a new PowerShell window, run `crypt` from any project. Crypt uses
the directory you launched it from as the workspace unless you pass `--cwd` or
set `CRYPT_ROOT`.

Useful commands:

```powershell
python main.py setup
python main.py doctor
python main.py project --refresh
python main.py project --json
python main.py learn list
python main.py learn search "pytest"
python main.py autonomy run
python main.py goals add "Launch a productized Crypt assistant" --success "first paying user"
python main.py webui --open
python main.py skills list
python main.py tasks list
python main.py --provider ollama --model gpt-oss:120b-cloud
python -m crypt
```

The WebUI is chat-first: talk to Crypt normally and it handles planning,
tools, learning, reflection, and skill promotion behind the scenes. There are
no prompt recipes to manage. Crypt also maintains a private `SOUL.md` that
shapes its voice and evolves from durable lessons, so it can feel consistent
without pretending to be literally conscious.

## Verify

```powershell
scripts\verify_core.ps1
```

Or run the checks directly:

```powershell
python -m ruff check .
python -m pytest
python main.py bench --bench-list
```

## Protected Core

Before changing runtime behavior, read [docs/CORE_CONTRACT.md](docs/CORE_CONTRACT.md).
The goal is simple: CryptCore can evolve, but the terminal coding harness must stay
solid while UI, desktop, web, and Agent D layers change around it.

For the reference-runtime audit and remaining parity gaps, see
[docs/REFERENCE_PARITY.md](docs/REFERENCE_PARITY.md).
