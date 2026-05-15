---
name: repo-verify
description: Run focused repository checks, interpret failures, and keep changes scoped before pushing.
---

# Repo Verify

Use this skill before claiming a code change is done.

## Workflow

- Run the narrowest check first for the files changed.
- Run the broader repo verification when the change touches shared runtime behavior.
- Treat failing tests as product feedback. Fix the cause or report the blocker.
- Do not hide unrelated dirty files by reverting them.
- Before pushing, check git status and stage only the files that belong to the task.

## CryptCore Defaults

- Python syntax: `python -m py_compile <files>`
- JavaScript syntax: `node --check core\webui_static\app.js`
- Focused WebUI tests: `pytest tests\test_webui.py`
- Full suite: `pytest`
- Quick release smoke: `scripts\verify_core.ps1 -Quick`
