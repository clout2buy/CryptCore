# Reference Runtime Parity Scan

Snapshot source: local clone of `https://github.com/openai/codex` at
`D:\tmp\openai-codex`.

## Reference Shape

OpenAI Codex is a Rust-first monorepo:

- `codex-rs/core`: agent business logic and provider/runtime orchestration.
- `codex-rs/tui`, `codex-rs/exec`, `codex-rs/cli`: interactive, headless, and
  multitool CLIs.
- `codex-rs/app-server*` and `app-server-protocol`: JSON-RPC app/IDE protocol,
  thread/turn/item lifecycle, command exec, file APIs, auth, skills, apps, and
  model metadata.
- `codex-rs/tool-api` and `codex-rs/tools`: extension-facing tool contracts and
  host-side tool planning/adaptation.
- `codex-rs/core-skills` and `core-plugins`: local/remote skills, plugin
  manifests, marketplace sync, and prompt injection.
- `codex-rs/mcp-server` and `rmcp-client`: MCP server/client surfaces.
- `codex-rs/sandboxing`, `linux-sandbox`, `windows-sandbox-rs`,
  `execpolicy`: OS-backed command sandboxing and prefix-rule policy.
- `sdk/python` and `sdk/typescript`: app-server clients and examples.

## CryptCore Status

CryptCore already covers the core coding-agent harness:

- Provider routing for Anthropic, OpenAI-compatible, Crypt OAuth,
  Gemini, and Ollama.
- Streaming think-act-observe loop, eager tool dispatch, tool schemas,
  approvals, redaction, evidence, sessions, compaction, memory, and traces.
- File, shell/background, git, web, planning, workspace, and typed subagent
  tools.
- JSONL app daemon for trusted UI clients.
- CI with lint, tests, package build, wheel smoke, benchmark smoke, and
  target-eval checks.

## Closed In This Pass

- Local skills: `core.skills` discovers `SKILL.md` bundles under project and
  user roots, lists them in the prompt, and injects active `$skill-name`
  instructions for the latest turn.
- MCP bridge: `core.mcp` plus the `mcp` tool can list configured servers,
  list server tools, and call tools through stdio JSON-RPC with normal approval
  and redaction.
- Prefix command policy: `~/.crypt/permissions.json` now supports
  `prefix_rules` with `allow`, `prompt`, and `forbidden` decisions for shell
  commands, matching the reference execpolicy shape.
- Doctor coverage: `/doctor` now reports visible skills and MCP config health.
- Project intelligence v2: workspace profiles now surface framework/library
  signals, entry points, CI files, and attention flags, with JSON export for
  UI clients and tooling.
- Structured learning loop: completed and failed turns are stored as episodes,
  completed turns derive reusable lessons from runtime evidence, and relevant
  learned context is retrieved into later prompts.

## Remaining Product-Scale Gaps

- OS-backed sandboxing: Crypt still relies on approval policy and command
  classification. Codex has platform sandbox backends for macOS, Linux, and
  Windows. This is release-significant if Crypt will run untrusted commands by
  default.
- Formal JSON-RPC app-server: Crypt's app daemon is JSONL and intentionally
  thin. Codex has a broad JSON-RPC thread/turn/item protocol with schema
  generation, file APIs, command exec streaming, auth endpoints, skill/app
  endpoints, and experimental capability gating.
- SDKs: Crypt does not ship Python/TypeScript clients for the app daemon.
- Plugin marketplace: Crypt has local skills and generic MCP, but no plugin
  manifest loader, marketplace install/update/remove flow, or remote bundle
  sync.
- Long-lived MCP/app processes: Crypt MCP calls are one-shot subprocesses. Codex
  manages startup status, OAuth, dynamic tool adaptation, and connector
  lifecycle.
- Release distribution: Codex ships standalone native binaries, npm, Homebrew,
  code signing, and remote app-server daemon flows. Crypt currently ships as a
  Python package/CLI core.

## Release Guidance

For a terminal-first Python release, the core harness is close once the test
suite is green. For a reference-class product release, do not mark parity
complete until the sandboxing, app-server protocol, plugin lifecycle, SDK, and
packaged distribution decisions are either implemented or explicitly deferred
in a release plan.
