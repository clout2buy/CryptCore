# Security

Crypt is a local-first agent harness. It may see source code, shell output,
credentials in environment variables, and generated artifacts. Treat every
release as a security-sensitive change.

## Credential Rules

- Never commit `.env`, auth files, trace logs, shell spill logs, or background job logs.
- OAuth tokens belong in `~/.crypt/auth.json`.
- Runtime API keys should come from environment variables or saved local setup.
- Use `.env.example` for documented variable names only. Leave values blank.
- Run a secret scan before pushing release branches.

## Built-In Protections

- common token formats are redacted before durable writes
- background logs and shell spill files are redacted
- dangerous shell commands require approval
- active HTML, SVG, and PDF artifacts do not auto-open
- `web_fetch` rejects private and rebinding targets by default
- worker subagents are scoped to explicit write paths

## Reporting

Open a private security report or contact the repository owner directly. Include
the affected version or commit, reproduction steps, and whether a token or local
file path was exposed.
