# Crypt Agent Phases 101-150

Second expansion track after the 1.0 release candidate. These phases focus on
making Crypt more durable, more visual, more self-repairing, and more useful as
a real autonomous operator while preserving explicit gates for external writes,
money, credentials, and destructive actions.

## Phase 101 - Runtime State Compactor

Compact bulky runtime snapshots into stable summaries so WebUI polling, prompt
context, daily briefs, and release manifests stay fast and readable.

Progress: added `core.runtime_compactor`, which summarizes large runtime
snapshots into stable key sections, counts, previews, size estimates,
compression ratio, and warning signals. WebUI Settings now shows compacted
snapshot size and warnings so the growing agent runtime stays readable instead
of flooding every prompt or panel with raw nested state.

## Phase 102 - Live Event Integrity Monitor

Detect event gaps, duplicated event ids, stalled streams, and stale thinking
events so live chat can prove whether it is actually streaming.

Progress: added `core.live_event_integrity`, which analyzes buffered WebUI
events for missing sequence numbers, duplicate sequence ids, unknown/invalid
events, stale active streams, and stalled thinking deltas. `/api/events` now
returns integrity metadata, the WebUI snapshot exposes stream health, and
Settings shows event issues so chat flicker/stalls can be diagnosed instead of
hand-waved.

## Phase 103 - Self-Healing WebUI Cache

Detect stale browser-side sessions, broken localStorage chat state, and
snapshot/feed mismatches, then provide safe reset and repair actions.

Progress: added `core.webui_cache_health` and browser-side cache self-repair.
The WebUI now backs up corrupt chat session localStorage to
`.corrupt.<timestamp>`, sanitizes cached sessions/messages before rendering,
tracks repaired browser cache state, and exposes the backend cache contract plus
client cache report in Settings.

## Phase 104 - Tool Failure Memory

Remember recurring tool failures by signature and teach Crypt the successful
recovery pattern before it retries the same broken path.

Progress: added `core.tool_failure_memory`, which classifies failed tool
results by stable signature, persists recurrence counts and recovery hints,
marks later successful calls as recovery patterns, surfaces the data in WebUI
Settings, and injects compact failure memory into future prompt context so
Crypt changes strategy instead of repeating the same broken call.

## Phase 105 - Agent Skill Quality Rubric

Score generated skills for safety, clarity, workflow usefulness, tests,
references, and tool boundaries before promoting them.

Progress: added `core.skill_quality_rubric`, which scores SKILL.md bundles
for metadata, trigger clarity, workflow instructions, verification, safety
boundaries, tool boundaries, and examples. Forged skills now write quality
status into lifecycle state before promotion, blocked skills are disabled, and
Skills/Settings show the rubric scores plus recommendations.

## Phase 106 - Browser/Desktop Permission HUD

Show visible operator status, current target, last action, and approval boundary
for browser and desktop operation.

Progress: added `core.operator_hud`, which summarizes browser and desktop
recordings into visible channels with status, target, last action, and approval
boundary. Home and Settings now show the HUD, and prompt context includes
active operator state so visual work stays explicit and approval-aware.

## Phase 107 - External Action Receipt Ledger

Record every approved external send/post/write/payment attempt with before/after
state, user approval, outcome, and rollback hint.

## Phase 108 - Mission Budget Ledger

Track time, model usage, estimated cost, revenue, and risk budget per mission.

## Phase 109 - Business CRM Starter

Create lightweight local lead/customer/opportunity records that missions can
update before any real external CRM connector exists.

## Phase 110 - Asset Library Manager

Index local images, videos, generated UI assets, documents, and website
artifacts with purpose, provenance, and reuse hints.

## Phase 111 - Knowledge Pack Builder

Bundle project docs, lessons, files, entities, and source summaries into
portable context packs for agents and long-running workers.

## Phase 112 - Prompt Injection Firewall

Scan web/file content for instruction-injection patterns and downgrade them into
quoted evidence instead of executable guidance.

## Phase 113 - Secret Rotation Advisor

Detect secret-looking incidents and produce rotation/cleanup checklists without
storing raw secrets.

## Phase 114 - Voice Wake Session Layer

Track voice-mode sessions, interruptions, confirmations, wake phrases, and
speaker preferences as first-class runtime state.

## Phase 115 - Screenshot Annotation Memory

Let Crypt save screenshot observations, UI defects, and visual verification
notes to reusable visual memory.

## Phase 116 - Accessibility And Motion Audit

Score the WebUI for keyboard reachability, contrast, text overflow, motion
safety, and touch ergonomics.

## Phase 117 - Autonomous Documentation Writer

Generate and maintain user-facing docs from shipped capabilities and runtime
features without copying internal implementation noise.

## Phase 118 - Structured Task Contracts

Convert vague requests into durable contracts with outcome, constraints,
acceptance checks, external gates, and stop conditions.

## Phase 119 - Agent Evaluation Arena

Run saved agent profiles against small task scenarios and score correctness,
initiative, safety, and evidence.

## Phase 120 - Capability Regression Dashboard

Track capability scores over time and flag regressions after upgrades.

## Phase 121 - Local Data Room

Create a privacy-first workspace for business files, notes, ledgers, and source
documents with indexing and access boundaries.

## Phase 122 - Autonomous Research Dossiers

Turn research tasks into source-backed dossiers with claims, citations, open
questions, and next collection steps.

## Phase 123 - Website Launch Factory

Promote website pipelines into launch packages with pages, assets, QA targets,
copy, analytics checklist, and deployment notes.

## Phase 124 - Revenue Experiment Planner

Create safe business experiments with hypothesis, setup, metrics, budget,
approval gates, and review cadence.

## Phase 125 - Local Notification Rules

Let Crypt create durable notification rules from user behavior and mission
deadlines, then surface them in daily briefs.

## Phase 126 - Autonomous Backup Policy

Plan and verify backups for project state, memory, sessions, release artifacts,
and user-generated work without copying secrets.

## Phase 127 - Recovery Playbook Generator

Generate playbooks from repair doctor, chaos checks, failed jobs, and tool
failure memory.

## Phase 128 - Model Route Benchmarking

Benchmark configured routes on small local scenarios and recommend models per
domain.

## Phase 129 - Persona Drift Guard

Let Crypt evolve tone and preferences while detecting robotic, sycophantic, or
overconfident drift.

## Phase 130 - Local Command Palette

Add a compact command palette for power actions without cluttering chat.

## Phase 131 - Mission Timeline Visualization

Show work threads, jobs, approvals, artifacts, and blockers as a timeline.

## Phase 132 - Agent Swarm Runbooks

Create reusable multi-agent runbooks for code, business, research, design, and
release work.

## Phase 133 - Connector Sandbox Simulator

Simulate external connectors and action receipts so workflows can be tested
without real accounts.

## Phase 134 - File Change Intent Ledger

Record why important files changed, which mission caused them, checks run, and
rollback hints.

## Phase 135 - Autonomous Dependency Watch

Detect outdated or risky dependencies and create safe upgrade missions.

## Phase 136 - Local Search Quality Audit

Score indexed context for freshness, coverage, duplication, and retrieval
quality.

## Phase 137 - Memory Privacy Classifier

Classify memory signals by sensitivity and scope before promotion.

## Phase 138 - Worktree Release Branch Assistant

Prepare release branches, changelog slices, PR bodies, and merge readiness
without touching unrelated user changes.

## Phase 139 - Project Health Score

Summarize repo health from tests, docs, CI state, risks, dependencies, and
runtime repair signals.

## Phase 140 - Business Ledger Importer

Import CSV/JSON income, expenses, leads, and conversions into local revenue ops.

## Phase 141 - Autonomous Form Filler Drafts

Prepare browser form-fill plans and visible previews while gating submission.

## Phase 142 - User Preference Conflict Resolver

Detect conflicting preferences across memory, trust calibration, persona, and
current instruction.

## Phase 143 - Mission Stop Conditions

Give every autonomous mission explicit done, pause, escalate, and ask conditions.

## Phase 144 - Local LLM Capability Probe

Probe local models for latency, context, tool-use suitability, and offline
readiness.

## Phase 145 - Visual UI Component Library

Extract stable WebUI components and patterns so new screens stay clean and
consistent.

## Phase 146 - Autonomous QA Evidence Pack

Bundle tests, screenshots, console logs, chaos checks, and release outputs into
shareable evidence packs.

## Phase 147 - Runtime Timeline Export

Export live replay, jobs, approvals, and mission events into markdown/JSON
timelines.

## Phase 148 - Self-Upgrade Safety Governor

Score proposed self-upgrades for blast radius, test plan, rollback, and user
value before execution.

## Phase 149 - Local App Health Daemon

Monitor backend/WebUI health, voice assets, event streams, and key state files
while the app is running.

## Phase 150 - Crypt 1.1 Release Candidate

Generate the second release candidate manifest after phases 101-149 with
evidence packs, regression dashboard, and rollout notes.
