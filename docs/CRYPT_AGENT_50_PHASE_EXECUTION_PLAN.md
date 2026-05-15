# CryptCore 50 Phase Agent Execution Plan

This is the core-agent build plan for making Crypt a simple chat-first personal
operator with durable autonomy underneath. This plan is intentionally not about
any game tracker or side project. It is about the CryptCore runtime, WebUI,
memory, missions, tools, skills, verification, and self-improvement loop.

The surface goal is simple: the user talks normally, and Crypt figures out the
workflow. The internal goal is disciplined autonomy: route the request, create
missions when needed, use tools, remember durable lessons, verify results, and
ask only when permission or missing information truly blocks progress.

## Guardrails

- Real external actions stay approval-gated: purchases, public posts, account
  creation, credential use, destructive filesystem actions, and irreversible
  business operations.
- Crypt can maintain a durable persona, but must not claim literal
  consciousness or sentience.
- Every phase should leave evidence: tests, smoke checks, logs, screenshots, or
  a clear reason verification was not possible.
- The UI should hide orchestration complexity by default. Panels are for
  inspection and control, not chores the user must manage.
- Each implementation pass should keep changes small enough to review and
  recover if something breaks.

## Phase 1 - Runtime Stability Baseline

Stop flicker, repeated chat resets, scroll jumps, duplicate handlers, stale DOM
patches, and polling churn across the WebUI.

Verification: backend tests, WebUI smoke test, browser console clean.

## Phase 2 - Live Event Contract [started]

Define one event schema for thinking, streaming text, tool starts, tool updates,
tool results, permission waits, errors, and final answers.

Verification: contract tests for every event type.

Progress:

- Added `core/live_events.py` as the shared event version/spec/normalizer for
  daemon and WebUI event buffers.
- Wired AppDaemon and WebUI event emission through the normalizer in
  compatibility mode so future events can roll out without breaking older UI.

## Phase 3 - True Live Chat Rendering [started]

Render assistant thinking, streaming response text, tool calls, and status
changes immediately inside the active chat without waiting for the next user
message or refresh.

Verification: browser test that observes intermediate states before completion.

Progress:

- Added a browser-side live-turn registry and restored request/session mapping
  from replayed live events.
- Preserved live timeline items in stored chat sessions so refreshes and session
  switches do not erase visible tool/thinking history.
- Thinking deltas now surface useful live text when the provider exposes them.

## Phase 4 - Minimal Composer [started]

Reduce the chat input to one natural box with voice, send, provider/model
dropdowns, and an advanced drawer for route/agent controls.

Verification: responsive screenshots and keyboard interaction smoke test.

Progress:

- Moved provider/model/route/agent and TTS controls behind an Options drawer so
  the default composer stays focused on mic, message, options, and send.
- Kept concise live status chips visible under the input for engine/voice state.

## Phase 5 - Provider And Model Registry [started]

Replace hardcoded display names with a clean provider/model registry that shows
simple names, capabilities, cost/latency hints, context limits, and fallback
routes.

Verification: registry unit tests and UI dropdown render test.

Progress:

- Added `core/model_registry.py` with clean labels, tiers, local/cloud flags, and
  capability hints for known provider models.
- Provider snapshots now include `modelMetadata`; the WebUI consumes it before
  falling back to local label formatting.

## Phase 6 - Intent Router V1 [started]

Turn a user message into a structured route: conversation, research, code,
business, mission, memory, browser, desktop, file, schedule, or external action.

Verification: routing fixtures with confidence and rationale checks.

Progress:

- Added `core/intent_router.py` for deterministic prompt classification with
  route role, confidence, durable-work signal, and approval-needed signal.
- WebUI prompt handling now emits `intentRouted`, adds compact intent context to
  the runtime prompt, and lets Crypt choose a backend route when the user leaves
  route selection on auto.

## Phase 7 - Clarification Policy

Teach Crypt when to act, when to ask one concise question, and when to ask for
approval because the next step has real-world impact.

Verification: decision tests for ambiguous and high-risk prompts.

## Phase 8 - Mission Object V2

Upgrade missions into durable objects with goal, status, priority, tasks,
blockers, due dates, artifacts, history, metrics, and next actions.

Verification: migration tests and mission CRUD tests.

## Phase 9 - Auto Mission Creation

Create missions automatically when the user asks for an outcome that requires
multi-step follow-through.

Verification: prompts that create, update, or decline mission creation.

## Phase 10 - Mission Brain Loop

Add a loop that chooses the next useful action for each active mission based on
status, blockers, due dates, and available tools.

Verification: deterministic mission-step planning tests.

## Phase 11 - Passive Memory V2

Capture durable user preferences, project facts, recurring tasks, tool quirks,
and lessons from normal conversation without requiring "remember this" prompts.

Verification: memory extraction fixtures with keep/drop decisions.

## Phase 12 - Memory Types And Confidence

Store memory by type with confidence, source, timestamps, decay, correction
history, and privacy sensitivity.

Verification: schema tests and retrieval filtering tests.

## Phase 13 - Memory Condenser

Periodically condense chat and mission history into compact long-term memory,
short-term context, and discarded noise.

Verification: condenser tests that preserve important facts and drop junk.

## Phase 14 - Persona Evolution

Let Crypt maintain a durable voice/persona profile that adapts to user
preferences while staying factual, bounded, and non-pretend-conscious.

Verification: persona update tests and prompt snapshot tests.

## Phase 15 - Tool Capability Registry

Record every tool by capability, risk level, inputs, outputs, examples,
permission needs, and recovery hints.

Verification: registry validation and tool selection tests.

## Phase 16 - Tool Recovery Engine

Detect common tool failures, recover with safer alternatives, and avoid dumping
raw tool errors into the chat unless they are genuinely useful.

Verification: simulated failure tests for edit, shell, browser, and network
errors.

## Phase 17 - Permission Boundary System

Classify actions as safe, approval-needed, sensitive, destructive, external, or
irreversible, and enforce the right boundary before execution.

Verification: policy tests and UI approval-state test.

## Phase 18 - Audit Log V2

Record what Crypt saw, decided, did, changed, verified, and still needs in a
clean audit trail.

Verification: log redaction tests and mission evidence checks.

## Phase 19 - Skill Loader

Support installing local skills, repo skills, and generated project skills with
metadata, trust review, examples, and smoke tests.

Verification: load a fixture skill and route a task to it.

## Phase 20 - Skill Forge

Let Crypt create its own reusable skills from repeated workflows, then test and
register them before use.

Verification: generated skill fixture, validation, and routing test.

## Phase 21 - Frontend Design Skill Integration

Codify the frontend design patterns used to build polished WebUI screens:
layout, motion, visual QA, screenshots, responsive checks, and non-generic
styling rules.

Verification: skill instructions present and runnable via a sample UI task.

## Phase 22 - Browser Operator V1

Add a browser lane for search, reading pages, screenshots, local app QA, and
structured extraction.

Verification: browser smoke test against the local WebUI.

## Phase 23 - Browser Operator V2

Add approval-gated form filling, account workflows, posting drafts, dashboard
checks, and evidence screenshots.

Verification: mocked form workflows and approval boundary tests.

## Phase 24 - Desktop Operator V1

Create a visual desktop operation layer that can move, click, type, inspect
screen state, and narrate visible actions.

Verification: local safe desktop task smoke test.

## Phase 25 - Visual Activity Feed

Show what Crypt is doing visually: current tool, browser screenshot, desktop
cursor action, mission step, and live reasoning summary.

Verification: UI smoke test with fake and real activity events.

## Phase 26 - Files And Artifact Studio

Group generated files, docs, sites, plans, scripts, screenshots, and reports by
mission with preview, status, and provenance.

Verification: create artifacts from a mission and display them.

## Phase 27 - Code Builder Loop

Standardize code work into inspect, plan, patch, test, review, summarize, and
commit-ready stages.

Verification: fixture repo task with tests and diff summary.

## Phase 28 - Reviewer Lane

Add a reviewer pass for nontrivial changes that catches regressions, missing
tests, unsafe assumptions, and UI quality issues.

Verification: reviewer fixture catches seeded bug.

## Phase 29 - Verifier Lane

Add a verifier pass that runs targeted checks, browser QA, screenshots, lint,
unit tests, and repo quick checks.

Verification: verification report attached to mission evidence.

## Phase 30 - Autonomous Scheduler

Let Crypt wake up for mission checks, safe read-only monitoring, follow-ups, and
scheduled work.

Verification: scheduled run fixture creates evidence without user input.

## Phase 31 - Monitor Framework

Add monitors for files, websites, GitHub, revenue dashboards, inboxes, calendars,
prices, analytics, or other configured data sources.

Verification: mock monitor detects a change and updates a mission.

## Phase 32 - Business Mission Template

Turn "start a business" into a mission tree: idea, market, offer, brand, landing
page, payment path, content, operations, analytics, and launch.

Verification: generated business mission with staged blockers and approvals.

## Phase 33 - Revenue And Metrics Layer

Support configured income tracking, expenses, funnels, conversions, analytics,
and weekly summaries.

Verification: local fixture dashboard with trend summary.

## Phase 34 - External Integration Manager

Create one settings surface for GitHub, email, calendar, storage, Slack/Discord,
Reddit, Stripe, analytics, and databases.

Verification: disabled-by-default connectors and scope display tests.

## Phase 35 - Credential And Secret Hygiene

Store credentials safely, redact secrets from logs, and prevent accidental
prompt/context leaks.

Verification: redaction tests and secret scan.

## Phase 36 - Contact And Account Memory

Track people, brands, accounts, businesses, channels, and relationships as typed
entities.

Verification: entity extraction and retrieval tests.

## Phase 37 - Knowledge Graph

Link missions, memories, files, skills, tools, contacts, artifacts, and facts so
Crypt can retrieve compact relevant context.

Verification: graph queries return useful scoped context.

## Phase 38 - Context Pack Builder

Build compact context packs for each request from memory, mission state, files,
skills, and active tools.

Verification: prompt snapshot tests with token budget checks.

## Phase 39 - Learning From Outcomes

After each task, record what worked, what failed, what the user corrected, and
what should change next time.

Verification: outcome lessons appear in future route/tool selection.

## Phase 40 - Self-Upgrade Idea Queue

Let Crypt propose self-upgrades from repeated friction, failed tools, user
feedback, and missing capabilities.

Verification: idea queue dedupes, ranks, and converts to missions.

## Phase 41 - Live Runtime Rebuild

Support safe local rebuild/restart flows that keep UI state, preserve sessions,
and report when the backend changed.

Verification: restart smoke test with active session preserved.

## Phase 42 - Plugin And MCP Gateway

Add a gateway for MCP servers/plugins with capability registry entries,
permission labels, health checks, and UI visibility.

Verification: mock MCP server registration and tool call.

## Phase 43 - Agent Profile System V2

Create durable specialist agents with provider/model, tools, memory scope,
personality constraints, and routing hints.

Verification: agent creation, edit, persistence, and invocation tests.

## Phase 44 - Agent Delegation Brain

Let main Crypt decide when to use a specialist agent, create one, update one, or
keep the task local.

Verification: delegation fixtures with correct agent choices.

## Phase 45 - Multi-Agent Work Threads

Run independent work threads with task state, artifacts, blockers, review, and
merge summaries.

Verification: two independent fixture threads complete without clobbering files.

## Phase 46 - UI Reconstruction Pass

Rebuild Home, Chat, Missions, Agents, Memory, Skills, Settings, and Activity into
a cleaner rounded interface with fewer panels and stronger motion.

Verification: desktop/mobile screenshots and console check.

## Phase 47 - Voice Pipeline V2

Improve speech-to-text toggle behavior, TTS voice options, emoji stripping,
interruptions, and speak-only-when-appropriate logic.

Verification: mocked voice events and TTS text sanitizer tests.

## Phase 48 - Mobile And Remote Access

Add secure optional remote/mobile access with authentication, limited scopes,
and backup/restore.

Verification: local auth flow and backup restore test.

## Phase 49 - Benchmark Suite

Create recurring benchmark tasks for chat, code, research, browser operation,
memory, missions, tools, and WebUI stability.

Verification: benchmark report saved as an artifact.

## Phase 50 - Release Train

Define a repeatable release process with changelog, tests, screenshots, upgrade
notes, known risks, rollback path, and GitHub push/PR behavior.

Verification: release checklist generated from a verified build.

## Overnight Execution Rules

Each unattended run should:

1. Inspect repository status and preserve unrelated changes.
2. Pick the highest-value incomplete phase or a small slice of it.
3. Implement only a scoped, recoverable increment.
4. Add or update tests when behavior changes.
5. Run focused verification, then broader quick checks when practical.
6. Record the completed slice, evidence, and next blocker in this file or the
   existing roadmap.
7. Avoid external state-changing actions without explicit approval.
