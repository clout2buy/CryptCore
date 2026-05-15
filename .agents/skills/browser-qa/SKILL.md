---
name: browser-qa
description: Verify local web apps visually and interactively with browser smoke tests, screenshots, and console checks.
---

# Browser QA

Use this skill when Crypt changes a web UI or needs to prove a local app works.

## Workflow

- Open the exact local URL the user is using.
- Reload after code changes so stale assets do not hide bugs.
- Inspect the visible DOM for the target controls before clicking.
- Exercise the broken path, not only the happy landing screen.
- Check console errors after interaction.
- Capture a screenshot when layout quality matters.

## What To Watch

- Chat messages appearing only after refresh.
- Scroll jumps while live events update.
- Dropdowns using default browser colors in a dark UI.
- Text clipping inside buttons, cards, and compact rows.
- Panels that look clickable but do nothing.

## Reporting

- Say what was verified and what still needs deeper testing.
- If the UI is still weak, identify the exact surface instead of calling the whole app broken.
