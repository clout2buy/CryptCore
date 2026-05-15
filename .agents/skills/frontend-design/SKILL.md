---
name: frontend-design
description: Build polished, production-grade web UI with strong visual direction, responsive layout, motion, and browser verification.
---

# Frontend Design

Use this skill whenever Crypt is building or cleaning up a web UI, dashboard,
landing page, app shell, chat surface, or visual component.

## Design Contract

- Pick one clear visual direction before editing: refined cockpit, cinematic glass, dense operator console, editorial, brutal minimal, or another coherent style that fits the product.
- Build the actual usable surface first. Avoid landing-page filler when the user needs a tool.
- Keep repeated panels calm and scannable. Use cards for items, not for every section inside another card.
- Make controls familiar: icon buttons for obvious tools, segmented controls for modes, toggles for binary settings, select/dropdown controls for model/provider choices, and compact rows for status data.
- Use restrained motion that helps orientation: short entrance fades, hover lift, running status pulses, and live activity indicators. Avoid constant layout-shifting animation.
- Text must fit at desktop and mobile widths. Prefer stable grid tracks, fixed control heights, and overflow handling.

## Chat UI Rules

- Chat is the primary surface. Keep it quiet, wide, readable, and stable while live events stream.
- Create an assistant placeholder immediately when work starts so the user sees thinking/live activity without refreshing.
- Do not re-render the whole chat view for status updates. Patch the existing message node.
- Keep model/provider controls near the composer but visually secondary.
- Live tool calls should appear as compact timeline rows below the active assistant bubble.

## Verification

- Run syntax checks for changed JS/CSS where possible.
- Open the local app in the browser and inspect the actual rendered UI after major visual changes.
- Test at least one live interaction path that the user complained about.
