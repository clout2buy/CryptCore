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

## Phase 7 - Clarification Policy [started]

Teach Crypt when to act, when to ask one concise question, and when to ask for
approval because the next step has real-world impact.

Verification: decision tests for ambiguous and high-risk prompts.

Progress:

- Added `core/clarification_policy.py` to convert routed prompts into execute,
  clarify, or approval-gate decisions.
- WebUI prompt context now includes the action policy so Crypt can keep moving
  on safe work while approval-gating public/external/destructive actions.

## Phase 8 - Mission Object V2 [started]

Upgrade missions into durable objects with goal, status, priority, tasks,
blockers, due dates, artifacts, history, metrics, and next actions.

Verification: migration tests and mission CRUD tests.

Progress:

- Extended work threads with task checklists and success metrics while keeping
  existing thread JSON backward-compatible.
- Mission UI rows now surface the next pending task before falling back to broad
  next-action text.
- Bumped work-thread storage to schema v2 and added prompt context for active
  task and success metric so the agent has durable mission operating state.

## Phase 9 - Auto Mission Creation [started]

Create missions automatically when the user asks for an outcome that requires
multi-step follow-through.

Verification: prompts that create, update, or decline mission creation.

Progress:

- Mission routing now accepts the structured intent route, so durable intents can
  create or reuse missions even when the mission keyword heuristic is not enough.
- The WebUI emits `missionMatched` for duplicate mission reuse, keeping the live
  chat transparent without asking the user to manage the mission panel.

## Phase 10 - Mission Brain Loop [started]

Add a loop that chooses the next useful action for each active mission based on
status, blockers, due dates, and available tools.

Verification: deterministic mission-step planning tests.

Progress:

- Added `core/mission_brain.py` to pick deterministic next steps from blockers,
  due dates, pending tasks, and explicit next-action state.
- Autonomy cycles now run the mission brain and record selected mission steps;
  prompt context includes a compact Mission Brain section.

## Phase 11 - Passive Memory V2 [started]

Capture durable user preferences, project facts, recurring tasks, tool quirks,
and lessons from normal conversation without requiring "remember this" prompts.

Verification: memory extraction fixtures with keep/drop decisions.

Progress:

- Added explicit passive-memory keep/drop classification with category,
  confidence, and reason fields.
- Passive lessons now distinguish persona, preference, project facts, tool
  quirks, recurring instructions, business context, agent signals, and UI
  preferences without requiring a manual "remember this" prompt.

## Phase 12 - Memory Types And Confidence [started]

Store memory by type with confidence, source, timestamps, decay, correction
history, and privacy sensitivity.

Verification: schema tests and retrieval filtering tests.

Progress:

- Bumped the Markdown memory journal to schema v2 with `memory_type`,
  confidence, sensitivity, decay, timestamps, and correction history fields.
- Added typed memory filtering so runtime code can retrieve memories by type,
  minimum confidence, and privacy sensitivity.

## Phase 13 - Memory Condenser [started]

Periodically condense chat and mission history into compact long-term memory,
short-term context, and discarded noise.

Verification: condenser tests that preserve important facts and drop junk.

Progress:

- Added `core/memory_condenser.py` to promote high-confidence typed working
  memory into long-term memory and discard stale low-confidence noise.
- Autonomy cycles now run the condenser and record memory promotion counts.

## Phase 14 - Persona Evolution [started]

Let Crypt maintain a durable voice/persona profile that adapts to user
preferences while staying factual, bounded, and non-pretend-conscious.

Verification: persona update tests and prompt snapshot tests.

Progress:

- Persona evolution now pulls from typed memory-journal persona/preference
  signals, not only structured lesson records.
- Learned persona bullets normalize sentience/consciousness language into a
  bounded "vivid persona, no literal consciousness claims" rule.

## Phase 15 - Tool Capability Registry [started]

Record every tool by capability, risk level, inputs, outputs, examples,
permission needs, and recovery hints.

Verification: registry validation and tool selection tests.

Progress:

- Tool definitions now support capability, risk, inputs, outputs, examples,
  permission needs, and recovery hints without requiring every existing tool to
  be rewritten.
- The registry infers capability cards for all loaded tools and exposes them in
  tool schemas plus WebUI tool previews.

## Phase 16 - Tool Recovery Engine [started]

Detect common tool failures, recover with safer alternatives, and avoid dumping
raw tool errors into the chat unless they are genuinely useful.

Verification: simulated failure tests for edit, shell, browser, and network
errors.

Progress:

- Added `core/tool_recovery.py` for reusable recovery advice and compact
  failure formatting.
- Tool dispatch now truncates huge raw failures and falls back to recovery
  advice instead of dumping noisy logs into chat.

## Phase 17 - Permission Boundary System [started]

Classify actions as safe, approval-needed, sensitive, destructive, external, or
irreversible, and enforce the right boundary before execution.

Verification: policy tests and UI approval-state test.

Progress:

- Added action-boundary classification for safe, approval-needed, sensitive,
  destructive, external, and irreversible tool calls.
- Runtime policy now warns on sensitive external reads while destructive command
  labels remain visible for the existing danger approval layer.

## Phase 18 - Audit Log V2 [started]

Record what Crypt saw, decided, did, changed, verified, and still needs in a
clean audit trail.

Verification: log redaction tests and mission evidence checks.

Progress:

- Evidence entries now append a persistent redacted audit JSONL under Crypt app
  data with saw/decided/did/changed/verified/needs phases.
- Added audit retrieval and summary helpers for task-scoped review.

## Phase 19 - Skill Loader [started]

Support installing local skills, repo skills, and generated project skills with
metadata, trust review, examples, and smoke tests.

Verification: load a fixture skill and route a task to it.

Progress:

- Skill discovery now returns trust level, examples, smoke tests, and source
  metadata for project, app, user, unknown, and blocked skills.
- The loader parses examples/smoke tests from frontmatter or Markdown sections
  while preserving existing prompt-injection blocking.

## Phase 20 - Skill Forge [started]

Let Crypt create its own reusable skills from repeated workflows, then test and
register them before use.

Verification: generated skill fixture, validation, and routing test.

Progress:

- Forged skills now include examples and smoke-test metadata in frontmatter.
- Forge results validate that the generated skill is discoverable and not
  blocked by the skill safety scan.

## Phase 21 - Frontend Design Skill Integration [started]

Codify the frontend design patterns used to build polished WebUI screens:
layout, motion, visual QA, screenshots, responsive checks, and non-generic
styling rules.

Verification: skill instructions present and runnable via a sample UI task.

Progress:

- Expanded the project `frontend-design` skill with examples, smoke tests,
  chat UI rules, and a reconstruction workflow.
- Added a repo fixture test that renders `$frontend-design` instructions from a
  sample UI task.

## Phase 22 - Browser Operator V1 [started]

Add a browser lane for search, reading pages, screenshots, local app QA, and
structured extraction.

Verification: browser smoke test against the local WebUI.

Progress:

- Added `core/browser_operator.py` to plan search, page-read, screenshot,
  extraction, and local-app QA browser lanes.
- Added a local WebUI HTTP smoke check for browser-operator verification.

## Phase 23 - Browser Operator V2 [started]

Add approval-gated form filling, account workflows, posting drafts, dashboard
checks, and evidence screenshots.

Verification: mocked form workflows and approval boundary tests.

Progress:

- Browser operator can now build structured jobs with steps, required evidence,
  and approval gates for forms, account workflows, posting, publishing, sending,
  and dashboard checks.
- Added approval-boundary tests for mocked form/post workflows.

## Phase 24 - Desktop Operator V1 [started]

Create a visual desktop operation layer that can move, click, type, inspect
screen state, and narrate visible actions.

Verification: local safe desktop task smoke test.

Progress:

- Added `core/desktop_operator.py` for visual desktop plans with inspect, move,
  click, type, screenshot, narration, and approval-gated sensitive actions.
- Added safe desktop planner tests for visible actions and password/login gates.

## Phase 25 - Visual Activity Feed [started]

Show what Crypt is doing visually: current tool, browser screenshot, desktop
cursor action, mission step, and live reasoning summary.

Verification: UI smoke test with fake and real activity events.

Progress:

- Added live-event contract entries for browser, desktop, and mission-step
  visual activity.
- The Core activity feed now renders distinct compact rows for tool, browser,
  desktop, mission, approval, and error activity.

## Phase 26 - Files And Artifact Studio [started]

Group generated files, docs, sites, plans, scripts, screenshots, and reports by
mission with preview, status, and provenance.

Verification: create artifacts from a mission and display them.

Progress:

- Added a persistent artifact studio index with preview, kind, provenance,
  status, and mission/thread ownership.
- `write_file` now registers generated files automatically and links them to
  the most recent active mission thread when appropriate.
- The WebUI Files view now shows mission-grouped artifact cards, summary
  counts, and workspace file fallback rows.

## Phase 27 - Code Builder Loop [started]

Standardize code work into inspect, plan, patch, test, review, summarize, and
commit-ready stages.

Verification: fixture repo task with tests and diff summary.

Progress:

- Added `core/code_builder.py` with deterministic inspect, plan, patch, test,
  review, summarize, and commit-ready stages.
- WebUI runtime hints now inject the builder loop automatically for coding
  requests, including likely files and checks.
- Added fixture tests for stage ordering, prompt context, and commit-ready
  reports.

## Phase 28 - Reviewer Lane [started]

Add a reviewer pass for nontrivial changes that catches regressions, missing
tests, unsafe assumptions, and UI quality issues.

Verification: reviewer fixture catches seeded bug.

Progress:

- Added `core/reviewer.py`, layering dedicated reviewer heuristics on top of
  the target-eval review checks.
- The reviewer flags dynamic execution, `shell=True`, swallowed broad
  exceptions, raw `innerHTML`, viewport-scaled type, transition-all UI flicker,
  and production changes without tests.
- The builder and system prompts now require a reviewer pass for nontrivial
  code edits before final summaries.

## Phase 29 - Verifier Lane [started]

Add a verifier pass that runs targeted checks, browser QA, screenshots, lint,
unit tests, and repo quick checks.

Verification: verification report attached to mission evidence.

Progress:

- Added `core/verifier_lane.py` to plan targeted syntax, unit, browser-marker,
  diff, and repo-quick checks from changed files.
- Verifier reports are written under the project state directory, recorded in
  the evidence ledger, linked into work-thread history, and registered in the
  artifact studio.
- Added tests for passing mission evidence, failing syntax checks, and browser
  QA planning markers.

## Phase 30 - Autonomous Scheduler [started]

Let Crypt wake up for mission checks, safe read-only monitoring, follow-ups, and
scheduled work.

Verification: scheduled run fixture creates evidence without user input.

Progress:

- Added `core/scheduler.py` for durable local scheduled jobs tied to goals and
  work threads.
- Autonomy cycles now run due scheduler jobs, record evidence, update thread
  history, and reschedule cadence-based reviews.
- WebUI snapshots and prompt context now include schedule state so Crypt can
  resume scheduled work without exposing more controls.

## Phase 31 - Monitor Framework [started]

Add monitors for files, websites, GitHub, revenue dashboards, inboxes, calendars,
prices, analytics, or other configured data sources.

Verification: mock monitor detects a change and updates a mission.

Progress:

- Added `core/monitors.py` with durable read-only file and mock/value monitors
  tied to missions and work threads.
- Autonomy cycles now run monitors, record monitor evidence, update goal
  results, and add thread history when changes are detected.
- WebUI snapshots and prompt context include monitor state for follow-up work.

## Phase 32 - Business Mission Template [started]

Turn "start a business" into a mission tree: idea, market, offer, brand, landing
page, payment path, content, operations, analytics, and launch.

Verification: generated business mission with staged blockers and approvals.

Progress:

- Added `core/business_mission.py` with a ten-stage launch template covering
  idea, market, offer, brand, landing page, payment, content, operations,
  analytics, and launch.
- Business work threads now receive full staged tasks, success metrics, and
  approval blockers for live payment, account, outreach, spending, and posting
  actions.
- WebUI prompt context includes the business template automatically when the
  user asks to start or operate a business.

## Phase 33 - Revenue And Metrics Layer [started]

Support configured income tracking, expenses, funnels, conversions, analytics,
and weekly summaries.

Verification: local fixture dashboard with trend summary.

Progress:

- Added `core/revenue.py` with a local ledger for revenue, expenses, visits,
  leads, conversions, channels, and notes.
- Added weekly summary and previous-window trend calculations for revenue,
  profit, funnel counts, conversion rate, and top channels.
- WebUI snapshots and prompt context now include revenue metrics when a
  workspace has business data.

## Phase 34 - External Integration Manager [started]

Create one settings surface for GitHub, email, calendar, storage, Slack/Discord,
Reddit, Stripe, analytics, and databases.

Verification: disabled-by-default connectors and scope display tests.

Progress:

- Added `core/integrations.py` with a disabled-by-default catalog for GitHub,
  email, calendar, storage, Slack, Discord, Reddit, Stripe, analytics, and
  databases.
- Each integration exposes category, status, approval requirement, and readable
  scopes so Crypt can explain access before using anything external.
- WebUI snapshots now include integration cards for future settings surfaces.

## Phase 35 - Credential And Secret Hygiene [started]

Store credentials safely, redact secrets from logs, and prevent accidental
prompt/context leaks.

Verification: redaction tests and secret scan.

Progress:

- Added `core/secret_hygiene.py` with text and workspace scanners for common
  API keys, tokens, secret assignments, private keys, and payment-card-shaped
  values.
- Scanner excerpts are redacted before reporting, and prompts now explicitly
  require secret-safe summaries, logs, screenshots, and artifacts.

## Phase 36 - Contact And Account Memory [started]

Track people, brands, accounts, businesses, channels, and relationships as typed
entities.

Verification: entity extraction and retrieval tests.

Progress:

- Added a workspace-scoped typed entity store for people, brands, businesses,
  accounts, channels, and relationships learned from normal chat.
- Entity memory dedupes mentions, redacts secret-looking details, writes a
  Markdown companion file, and feeds compact non-private context back into the
  runtime prompt.
- WebUI snapshots and the Memory view now surface entity counts and previews
  without making the user manually maintain contacts.

## Phase 37 - Knowledge Graph [started]

Link missions, memories, files, skills, tools, contacts, artifacts, and facts so
Crypt can retrieve compact relevant context.

Verification: graph queries return useful scoped context.

Progress:

- Added a computed workspace knowledge graph that links goals, work threads,
  memory signals, typed entities, artifacts, skills, tools, and top-level files.
- Query retrieval scores node overlap plus graph connectivity so prompt context
  can pull the most relevant mission/entity/artifact/tool state automatically.
- WebUI snapshots now include graph counts and previews, and runtime prompts get
  a compact graph context pack for each user message.

## Phase 38 - Context Pack Builder [started]

Build compact context packs for each request from memory, mission state, files,
skills, and active tools.

Verification: prompt snapshot tests with token budget checks.

Progress:

- Added a budgeted context-pack builder that ranks mission state, graph hits,
  memory, typed entities, matching files, relevant skills, and available tools
  for each request.
- Context packs estimate token use, omit lower-value items when the budget is
  full, and exclude private entity memory from prompt injection.
- WebUI snapshots expose a compact pack preview, and chat prompts now receive a
  request-scoped context pack automatically.

## Phase 39 - Learning From Outcomes [started]

After each task, record what worked, what failed, what the user corrected, and
what should change next time.

Verification: outcome lessons appear in future route/tool selection.

Progress:

- Task outcomes now create lessons for both completed and failed runs, including
  concrete recovery hints for schema, read-before-edit, permission, and timeout
  failures.
- The desktop/WebUI daemon records outcome episodes after live turns and emits a
  live outcome-learning event when new lessons are saved.
- User corrections in normal chat are captured as durable feedback lessons so
  future routing and tool behavior can adapt without manual memory commands.

## Phase 40 - Self-Upgrade Idea Queue [started]

Let Crypt propose self-upgrades from repeated friction, failed tools, user
feedback, and missing capabilities.

Verification: idea queue dedupes, ranks, and converts to missions.

Progress:

- Added a durable self-upgrade queue that ranks ideas from user corrections,
  failure/recovery lessons, reflections, and open-loop memory.
- Upgrade ideas dedupe by normalized title, accumulate supporting signals, and
  can convert into full autonomous missions/work threads.
- Autonomy cycles now refresh the self-upgrade queue, and WebUI/runtime context
  can surface the highest-priority proposed upgrades.

## Phase 41 - Live Runtime Rebuild [started]

Support safe local rebuild/restart flows that keep UI state, preserve sessions,
and report when the backend changed.

Verification: restart smoke test with active session preserved.

Progress:

- Added a runtime rebuild planner with verification commands, restart command,
  preservation notes, and changed-file tracking.
- Rebuild records are stored per workspace, and snapshots report when backend
  code changed after the last rebuild record.
- WebUI/runtime context now exposes rebuild status so Crypt can recommend safe
  verification and restart without losing durable sessions or local UI state.

## Phase 42 - Plugin And MCP Gateway [started]

Add a gateway for MCP servers/plugins with capability registry entries,
permission labels, health checks, and UI visibility.

Verification: mock MCP server registration and tool call.

Progress:

- Added an MCP/plugin gateway layer that lists configured servers plus
  workspace mock servers with capability, risk, and permission labels.
- Gateway health checks can probe real configured MCP servers or validate mock
  servers safely, and mock tool calls provide deterministic local verification.
- WebUI snapshots and runtime prompt context now expose gateway server/tool
  visibility without requiring the user to know MCP internals.

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
