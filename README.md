# CryptCore

CryptCore is the protected Python runtime and terminal coding harness behind
Crypt. It owns the agent loop, provider routing, typed tools, approvals,
sessions, memory, subagents, safety checks, tests, and release gates.

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

Useful commands:

```powershell
python main.py setup
python main.py doctor
python main.py --provider ollama --model gpt-oss:120b-cloud
python -m crypt
```

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
