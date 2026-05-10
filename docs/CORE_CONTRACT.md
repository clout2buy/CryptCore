# CryptCore Contract

CryptCore is the stable engine under Crypt and Agent D. UI layers may change quickly,
but this core must preserve the coding harness behavior that makes Crypt useful.

## Must Keep Working

- Terminal startup through `python main.py` and `python -m crypt`.
- Provider routing for configured Anthropic, OpenAI-compatible, ChatGPT/Codex OAuth,
  Gemini, and Ollama backends.
- Interactive setup, login, logout, doctor, benchmark, eval-target, and session resume
  commands.
- File tools: read, media read, list, glob, grep, edit, multi-edit, and write.
- Shell tools: foreground commands and background process start, poll, and kill.
- Git tools: status/log/diff style inspection, branch, stage, and commit helpers.
- Web tools: search and fetch with local-network/private-address protections.
- Planning and memory tools: plan presentation, todos, ask-user, durable memory.
- Subagent tools: spawn, list, message, output, stop, and cleanup agents.
- Runtime safety: approval modes, read-before-edit checks, stale write protection,
  shell danger checks, scoped worker writes, trace redaction, and session redaction.
- Evidence and verification paths used by production runtime, target eval, and tests.

## Allowed To Change

- Internal implementation details when tests and behavior stay compatible.
- Provider/model inventory as long as existing configured providers still route.
- Tool internals when schemas, approval behavior, and output contracts remain stable.
- New tools, skills, memory features, and provider adapters.
- UI clients that consume the runtime, including desktop, web, or Agent D shells.

## Not Core

- Electron renderer code.
- Desktop-only styling and layout.
- Packaged app assets, icons, installers, and release output.
- Experimental Agent D UI/personality work.
- Generated caches, traces, eval outputs, and local auth files.

## Change Rule

Any change that touches `core/`, `tools/`, `main.py`, or provider/session behavior
should either preserve existing tests or add focused tests that describe the new
contract. The CLI harness is the source of truth.
