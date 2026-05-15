# Crypt Agent Roadmap

This roadmap is the long-form direction for turning CryptCore from a local
agent runtime plus WebUI into a self-improving personal operator. The goal is a
simple chat-first experience where the user can speak normally and Crypt handles
planning, tools, memory, verification, and follow-through behind the scenes.

For the expanded execution sequence used by unattended core-agent work, see
`docs/CRYPT_AGENT_50_PHASE_EXECUTION_PLAN.md`.

## Product North Star

Crypt should feel like one capable assistant, not a pile of modes. The user
should be able to say "start this business", "learn this tool", "post this when
ready", "reverse engineer this service", "watch my revenue", or just talk, and
Crypt should decide the workflow:

- understand the intent
- inspect the workspace and relevant outside context
- create or update goals
- use tools and skills safely
- ask only when permission or missing information is genuinely required
- remember durable preferences and lessons
- verify work before presenting it
- explain what changed in plain language

Crypt can have a durable voice and personality layer, but it must not claim
literal consciousness. The implementation target is continuity, initiative,
judgment, and taste.

## Phase 1 - Stabilize The WebUI Runtime

Stop all accidental rerenders, flicker, scroll jumps, and duplicate event
handlers. Chat, panels, drawers, and background polling need to update in place.
The UI should feel calm even while the backend streams tokens and tool events.

Done means:

- chat token streaming patches existing DOM nodes
- snapshot polling never resets the active panel
- long outputs keep scroll behavior predictable
- console errors stay clean during normal use

## Phase 2 - Chat-First Command Router

Build a real intent router in the backend so the UI does not need prompt
recipes. A user message should become a structured route such as conversation,
research, code, business, schedule, monitor, learn, browse, or external action.

Done means:

- each prompt receives a route with confidence and rationale
- low-confidence routes ask one concise clarification
- high-confidence routes execute the next safe step
- route decisions are logged for learning

## Phase 3 - Mission Objects

Replace loose goals with richer mission objects. A mission is an outcome Crypt
can pursue over time, with tasks, checklists, artifacts, cadence, success
metrics, blockers, and history.

Done means:

- missions can be created from chat automatically
- each mission has status, priority, next action, and due signals
- the WebUI shows active mission progress without clutter
- completed missions produce lessons and reusable playbooks

## Phase 4 - Durable Workspace Memory V2

Upgrade memory from simple lessons to typed memory: user preferences, project
facts, contacts, business assumptions, recurring workflows, credentials needed,
and tool quirks.

Done means:

- memory is typed and searchable
- memory has confidence, source, and last-used timestamps
- bad memories can be corrected or retired
- memory retrieval is scoped to the current request

## Phase 5 - Skill Acquisition Pipeline

Make "I found this skill" a first-class workflow. Crypt should inspect a skill,
evaluate trust, install or sandbox it, test it, document how to use it, and add
it to the routing layer.

Done means:

- skill import supports local folders and trusted Git repos
- risky instructions are flagged before activation
- a smoke test validates each skill
- successful skill usage creates examples and routing hints

## Phase 6 - Tool Capability Registry

Teach Crypt what every tool can do, what it costs, what permission it needs, and
what evidence proves success. The router should pick tools by capability rather
than hardcoded names.

Done means:

- every tool has category, risk, inputs, outputs, and examples
- tool selection can explain why a tool was chosen
- failed tool calls update recovery hints
- UI panels expose tools by capability, not raw schema dumps

## Phase 7 - Browser Operator

Add a browser automation lane for research, form filling, dashboards, posting,
and local UI verification. External actions such as posting or purchases remain
approval-gated.

Done means:

- browser sessions are task-scoped and logged
- Crypt can search, inspect, screenshot, and summarize pages
- state-changing actions request permission at the point of impact
- completed browser work leaves evidence in the mission log

## Phase 8 - Business Builder Mode Without Modes

Support natural requests like "start a business for me" by expanding them into a
mission tree: market research, offer design, landing page, payment setup,
content plan, operations, metrics, and launch checklist.

Done means:

- business requests create a mission with milestones
- Crypt can generate artifacts and track dependencies
- revenue and analytics monitors can be attached later
- every external account/action has a permission boundary

## Phase 9 - Autonomous Scheduler

Turn cadence into actual scheduled work. Crypt should wake up for due missions,
run safe checks, summarize results, and queue approval-needed actions.

Done means:

- schedules persist across restarts
- safe read-only checks can run unattended
- external writes are prepared but not sent without permission
- the WebUI shows upcoming and completed autonomous runs

## Phase 10 - Reviewer And Verifier Lanes

Every nontrivial change should go through a builder/reviewer/verifier pattern.
This can be a local subagent or a staged internal loop, but the result must be
evidence-driven.

Done means:

- code changes include targeted tests or a reason tests were not run
- reviewer findings are stored with the task
- verifier output is attached as evidence
- failures become lessons

## Phase 11 - Artifact Studio

Crypt needs a clean workspace for generated artifacts: docs, landing pages,
spreadsheets, images, scripts, PR descriptions, business plans, and dashboards.

Done means:

- artifacts have previews and provenance
- generated files are grouped by mission
- edits can be requested from chat
- final artifacts have verification status

## Phase 12 - Model And Provider Intelligence

Crypt should choose the right model/provider route based on task type, latency,
cost, context size, coding strength, and privacy needs.

Done means:

- routes have capabilities and constraints
- the active route is visible but not something the user must manage
- failed provider calls recover to another route when possible
- route performance becomes part of learning

## Phase 13 - Knowledge Graph

Add a lightweight graph over missions, memories, files, skills, tools, contacts,
business entities, and artifacts. This lets Crypt connect old work to new
requests without dumping full transcripts into context.

Done means:

- graph nodes have type, source, confidence, and links
- retrieval returns compact, relevant context
- stale graph facts can be invalidated
- the UI can show "why Crypt knows this"

## Phase 14 - Personal Operating System Panels

Keep chat central, but give panels real value: Mission Control, Calendar,
Revenue, Inbox, Files, Browser, Memory, Skills, Tools, Models, Settings, and
Audit Log.

Done means:

- every panel supports a real workflow
- panels are inspectable, not required orchestration
- chat can jump to the right panel when useful
- layout is responsive, calm, and flicker-free

## Phase 15 - External Integrations

Add connectors for GitHub, Gmail/Outlook, Calendar, Drive, Slack/Discord, Reddit,
Stripe, analytics, and databases through explicit config and permissions.

Done means:

- integrations are disabled until configured
- each integration has clear scopes and permission language
- writes are approval-gated
- monitors can read configured dashboards safely

## Phase 16 - Trust, Safety, And Audit

Autonomy only works if the user can trust it. Build a clear audit trail for what
Crypt saw, decided, changed, and still needs.

Done means:

- every action has timestamp, input, tool, output, and permission state
- secret redaction applies before storage
- risky actions are classified consistently
- the WebUI can show "what happened" without exposing noise

## Phase 17 - Self-Upgrade Loop

Crypt should be able to propose and implement upgrades to itself through the
same disciplined coding loop used for user projects.

Done means:

- self-upgrade ideas become missions
- changes are scoped and tested
- risky architecture changes require explicit approval
- upgrade attempts produce lessons whether they succeed or fail

## Phase 18 - Voice And Presence

Add optional voice input/output and a less robotic interaction style. This is
about comfort and continuity, not pretending to be alive.

Done means:

- voice can be toggled on/off
- interruptions are handled cleanly
- persona preferences are durable
- Crypt can be casual without losing technical rigor

## Phase 19 - Deployment And Remote Access

Make Crypt usable outside the local desktop: secure tunnel, authenticated
mobile access, hosted mission runners, and backup/restore.

Done means:

- local-only remains the default
- remote access requires auth and explicit enablement
- mission runners have limited scopes
- backups can restore memory, missions, skills, and config

## Phase 20 - Quality Bar And Release System

Build a repeatable release train so Crypt keeps improving without breaking the
assistant experience.

Done means:

- WebUI smoke tests cover major panels
- backend tests cover missions, memory, scheduling, and tool routing
- benchmark tasks measure real agent capability
- release notes explain user-visible changes
- regressions become tracked missions

## Immediate Next Build Order

The next serious implementation sequence should be:

1. finish WebUI stability and output streaming
2. add backend intent routing
3. upgrade goals into missions
4. build mission-aware autonomy
5. add skill acquisition and validation
6. add browser operator workflows
7. build business mission templates
8. add scheduled monitors
9. harden audit logs and permission boundaries
10. expand integrations only after the core loop is reliable

This order matters because autonomy without stable memory, missions, routing,
and audit trails becomes chaotic. Crypt should become more independent by
becoming more structured underneath, while staying simple on the surface.

## Current Shipped Increment

The first concrete slice of this roadmap is now in the WebUI/runtime:

- chat polling skips unchanged shell/session/core DOM writes, so the message
  feed no longer resets every polling tick
- the composer is simplified around one natural input, voice, provider, model,
  route, and optional saved agent
- voice input uses a restart-tolerant Web Speech toggle instead of flipping off
  immediately after a short/no-speech event
- saved agent profiles persist under the workspace and update the matching
  runtime route so delegated work uses the selected provider/model
- the UI has an Agents panel for creating reusable specialists without making
  the user hand-orchestrate every task
- chat sessions persist locally and "New Session" no longer destroys the old
  conversation list
- passive memory captures useful user signals from normal chat and refreshes
  Crypt's managed soul/persona block automatically
