# Crypt Agent Phases 51-100

This plan extends the verified 1-50 execution run. It is based on the remaining
gaps exposed by the release checklist, benchmarks, WebUI state, and autonomous
mission/memory work.

## Phase 51 - Capability Matrix

Build a runtime matrix showing what Crypt can do, which modules power it, what
is ready, and what verification backs it.

Progress: implemented `core.capability_matrix`, added it to the WebUI snapshot,
and surfaced a compact home-screen capability panel.

## Phase 52 - Autonomy Contract Profiles

Add named autonomy profiles for casual chat, build work, business operations,
browser operation, desktop operation, and high-risk external actions.

Progress: added `core.autonomy_contracts`, selected contracts during prompt
routing, exposed contracts in the WebUI snapshot/settings, and inject the
selected contract into runtime hints.

## Phase 53 - External Action Draft Queue

Create a queue for emails, Reddit posts, purchases, DMs, account actions, and
other external effects that must be drafted, reviewed, and approved.

Progress: added `core.external_drafts`, automatically queues external-action
prompts into pending approval drafts, exposes them in WebUI snapshot/jobs, and
records draft lifecycle events.

## Phase 54 - Business Entity Registry

Track businesses, offers, products, customers, channels, assets, domains,
expenses, and revenue streams as first-class entities.

Progress: added `core.business_entities`, passively extracts business objects
from chat, writes JSON plus Markdown registry artifacts, injects registry
context into prompts, and surfaces business entities in WebUI memory.

## Phase 55 - Website Generator Pipeline

Package frontend-design workflows into a repeatable site/app generator with
brief, implementation, preview, QA, and iteration stages.

Progress: added `core.website_pipeline`, creates/matches site/app workflows
from natural prompts, tracks stages and artifacts, injects website pipeline
context into prompts, and surfaces site pipelines in WebUI files.

## Phase 56 - Revenue Operations Dashboard

Upgrade revenue tracking into goals, forecasts, expenses, channel performance,
and next-action recommendations.

Progress: added `core.revenue_ops` with revenue targets, 30-day forecasts,
channel performance, recommendation logic, WebUI snapshot/home panel, and
runtime prompt context.

## Phase 57 - Visual Browser Recorder

Record browser navigation, screenshots, console errors, and visual QA notes into
mission artifacts.

Progress: added `core.browser_recorder`, records browser smoke sessions,
screenshots, console errors, QA notes, artifact links, WebUI snapshot/jobs, and
runtime prompt context.

## Phase 58 - Desktop Operation Recorder

Record desktop action intent, mouse/keyboard operations, screenshots, and safety
gates into live mission timelines.

Progress: added `core.desktop_recorder`, records planned desktop actions,
approval-gated steps, screenshots as artifacts, safety notes, WebUI snapshot/jobs,
and runtime prompt context.

## Phase 59 - Skill Lifecycle Manager

Version, enable, disable, update, and audit local skills with provenance and UI
state.

Progress: added `core.skill_lifecycle`, lifecycle disable/enable markers,
version hashes, audit cards, WebUI snapshot/skill stats, and prompt context for
current skill state.

## Phase 60 - Agent Team Templates

Define reusable teams like business launch, frontend build, bug fix, research,
release, and content operations.

Progress: added `core.agent_team_templates`, reusable team definitions, profile
creation, multi-agent thread creation, WebUI snapshot/agents panel, and prompt
context for team selection.

## Phase 61 - Memory Importance Scoring V2

Score memory candidates by recurrence, user preference, project value, risk,
and future usefulness.

Progress: added `core.memory_importance`, integrated scoring into passive
Markdown memory promotion, saves importance breakdowns per signal, and keeps
confidence/promotion tied to recurrence, preference, project value, risk, and
future usefulness.

## Phase 62 - Memory Garbage Collection

Expire weak short-term memory, merge duplicates, and preserve durable facts in a
clean Markdown ledger.

Progress: upgraded `core.memory_condenser` to merge duplicate working/long-term
signals, preserve hits/tags/confidence/importance, dedupe long-term promotion,
and report merged/discarded/promoted counts.

## Phase 63 - Persona Governance

Let Crypt evolve voice/persona while keeping safety constraints and user
preferences visible and testable.

Progress: added `core.persona_governance`, audits soul/persona rules, detects
forbidden sentience/external-action claims, exposes governance in WebUI persona
state, and injects persona rules into prompt context.

## Phase 64 - Autonomous Skill Creation From Outcomes

Create/update SKILL.md files from repeated successful task episodes, not just
manual forge requests.

Progress: added `core.skill_outcome_autoforge`, detects repeated successful
task patterns, scores confidence from lessons/checks/changed areas, promotes
ready patterns into project-local SKILL.md files during autonomy cycles, and
surfaces outcome candidates in the WebUI skills panel and runtime hints.

## Phase 65 - Tool Capability Cards

Expose every tool with scope, risk, permission needs, examples, and live usage
state in WebUI.

Progress: added `core.tool_capability_cards`, builds first-class cards from the
tool registry, enriches them with runtime policy risk, examples, recovery hints,
and audit/evidence usage counts, injects tool-card context into prompts, and
rebuilds the WebUI tools view around the live arsenal instead of a flat list.

## Phase 66 - Smart Model Router V2

Route by task category, cost, latency, context length, tool use, and required
reasoning depth.

Progress: added `core.smart_model_router`, classifies prompts by intent,
reasoning need, latency/cost bias, context size, and tool load, routes within
the configured provider first, emits live `modelRouted` events for auto-routed
turns, and surfaces router examples in the WebUI models panel and runtime
prompt context.

## Phase 67 - Provider Health Monitor

Track provider readiness, auth expiration, latency, errors, and recommended
fallbacks.

Progress: added `core.provider_health`, persists provider successes/failures
and latency, reports auth readiness and OAuth expiry windows, recommends a
fallback provider, records health after app turns, and surfaces provider health
in snapshots, settings UI, and runtime prompt context.

## Phase 68 - Mission Scheduler V2

Schedule durable missions with recurrence, due dates, pause/resume, results,
and escalation rules.

Progress: upgraded `core.scheduler` with priority, escalation rules,
pause/resume, last-run timestamps, missed-run tracking, overdue escalation
notes, and a scheduler snapshot. The WebUI mission panel now shows scheduled
jobs alongside work threads and goals.

## Phase 69 - Notification Center

Surface finished work, blockers, approvals, reminders, and failed background
jobs in one clean feed.

Progress: added `core.notification_center`, a persistent unread/read/archive
feed for approvals, task completions, failures, reminders, and blockers. App
turns and approval waits now create notifications, snapshots expose unread and
critical counts, and the home UI shows a compact notification center.

## Phase 70 - Artifact Dependency Graph

Connect generated files, missions, memories, agents, checks, and releases into
a navigable dependency graph.

Progress: added `core.artifact_graph`, which builds nodes and edges for
workspace artifacts, goals, work threads, learned lessons, saved agents,
verification checks, and release records. The WebUI files panel now surfaces
graph counts and recent dependency links.

## Phase 71 - Self-Upgrade Sandbox

Plan self-upgrades in an isolated branch/worktree, run checks, then propose the
merge.

Progress: added `core.self_upgrade_sandbox`, which turns upgrade ideas into
isolated branch/worktree plans with default verification commands, records
changed paths and check results, tracks merge readiness, and exposes sandbox
state in the WebUI settings panel and runtime prompt context.

## Phase 72 - Patch Risk Classifier

Classify code changes by blast radius, security, UI, data, and test coverage
before commit.

Progress: added `core.patch_risk`, which inspects changed paths, grades blast
radius plus security/UI/data/test surfaces, recommends focused checks, and
injects the current patch risk into WebUI settings and runtime prompt context.

## Phase 73 - Release Screenshot Pipeline

Capture desktop/mobile screenshots for UI-heavy releases and attach them to the
release checklist.

Progress: added `core.release_screenshots`, which creates desktop/mobile
screenshot manifests, registers captured images as verified artifacts, writes a
Markdown capture plan beside each release checklist, and feeds those targets
into `core.release_train` plus `python main.py release --release-ui-url`.

## Phase 74 - Local Search Index

Index project docs, memories, missions, artifacts, and skills for fast context
retrieval.

Progress: added `core.local_search_index`, a cached lexical index over
workspace docs, memory/lessons, missions, work threads, artifacts, and skills.
Runtime prompt context now includes top local hits for the current user request,
and the WebUI surfaces document/token/source counts.

## Phase 75 - Document/Spreadsheet/Presentation Office Layer

Turn office-style output into durable artifacts with verification and previews.

Progress: added `core.office_layer`, which creates/registers office artifacts,
validates Markdown/text/CSV/PDF/DOCX/XLSX/PPTX files, records previews and
checks, links them into Artifact Studio, and surfaces office output in WebUI
Files plus runtime prompt context.

## Phase 76 - Business Launch Autopilot

Create a full business launch mission with offer, site, content, channels,
analytics, revenue tracking, and approval gates.

Progress: added `core.business_launch`, which turns launch/business requests
into connected mission threads, website pipelines, revenue targets, office
briefs, launch stages, and explicit approval gates. The WebUI now shows launch
autopilot state in Missions and emits live launch updates from normal chat.

## Phase 77 - Content Operations Planner

Plan posts, scripts, videos, thumbnails, channels, drafts, approvals, and
performance tracking.

Progress: added `core.content_ops`, which creates durable content campaigns,
channel-specific posts/scripts/video/thumbnail/email pieces, queues each
external-facing piece into the approval draft system, records performance
metrics, and exposes content ops in Missions plus runtime prompt context.

## Phase 78 - Account And Credential Vault Interface

Track credential needs without exposing secrets; store references, not raw
passwords or tokens.

Progress: added `core.credential_vault`, a reference-only credential tracker
that records service/account needs, rejects raw secret-looking values, observes
credential requirements from chat, injects safe references into prompt context,
and surfaces vault status in WebUI settings.

## Phase 79 - Approval Policy Builder

Let users configure what Crypt can do automatically versus what needs approval.

Progress: added `core.approval_policy`, which persists allow/draft/ask/block
rules, seeds safe defaults for external sends, payments, credential use, local
build work, and destructive operations, exposes decisions in prompt context, and
surfaces the policy summary in WebUI settings.

## Phase 80 - Live Tool Replay

Replay tool calls, command output, browser events, and desktop events in WebUI.

Progress: added `core.live_replay`, a persistent replay ledger for tool calls,
tool results, command output, browser/desktop activity, mission steps, and
approval events. WebUI now records replay-worthy events automatically and shows
recent replay items on the home panel and prompt context.

## Phase 81 - Job Queue Persistence

Persist background jobs with restart recovery, status, logs, and cancellation.

Progress: added `core.job_queue`, which persists queued/running/completed/
failed/cancelled/interrupted jobs with logs, attempts, cancellation requests,
and restart recovery. WebUI startup now marks stale running jobs interrupted and
the Jobs panel shows persistent queue state.

## Phase 82 - Agent Cost And Latency Ledger

Track model/provider usage, latency, success, and rough cost where available.

Progress: added `core.model_usage_ledger`, which records provider/model runs,
success/failure, latency, estimated token split, and rough estimated cost. The
AppDaemon now writes usage entries after model turns, and the WebUI surfaces
usage totals, cost estimates, and latency in Home/Settings plus prompt context.

## Phase 83 - Research Source Manager

Save web sources, summaries, quotes, dates, and trust notes as reusable
research artifacts.

Progress: added `core.research_sources`, which saves/dedupes URL sources,
summaries, short quote excerpts, published dates, tags, and trust notes. Chat
URL observations now create reusable source records, Memory shows source counts,
and prompt context can recall relevant research sources.

## Phase 84 - Safer Public Posting Flow

Draft, preview, cite, approval-check, and log public posts without accidental
posting.

Progress: added `core.public_posting`, which creates approval-gated public post
drafts, requires citations for factual/performance claims, links citations into
the research source manager, stores approval/published state, and surfaces
public post previews in the WebUI Jobs panel and runtime prompt context.

## Phase 85 - File Workspace Map

Map important project folders, generated artifacts, ignored files, and safe edit
zones.

Progress: added `core.workspace_map`, which classifies top-level workspace
items, source-safe edit zones, generated/local-only areas, ignored patterns, and
protected risky paths. The WebUI Files view now shows safe zones and avoid
zones, and runtime prompt context tells Crypt where to edit and what not to
commit.

## Phase 86 - Data Import Layer

Import CSV, JSON, Markdown, notes, screenshots, and browser exports into
entities/memory/missions.

Progress: added `core.data_importer`, which inspects CSV/TSV, JSON/JSONL,
Markdown/notes, images, and browser exports; registers imports as artifacts;
feeds useful summaries into memory and entity extraction; creates mission
follow-ups for goal-like notes; and surfaces imports in WebUI Files plus runtime
prompt context.

## Phase 87 - Personal Operating System Mode

Unify chat, reminders, missions, files, browser, voice, and business work into
a simplified daily command surface.

Progress: added `core.personal_os`, which composes missions, memory, approvals,
notifications, files, voice, jobs, and business signals into one command
surface. The WebUI Home panel now uses this Personal OS layer for status cards,
daily next actions, and operating lanes, while prompt context tells Crypt to
route plain-language asks without requiring orchestration from the user.

## Phase 88 - Voice Conversation Mode

Full duplex-feeling local voice loop with interruption, short responses, and
transcript memory.

Progress: added `core.voice_conversation`, a durable local voice session ledger
that records listening, transcript, reply, interruption, stop, and error events,
promotes useful voice transcripts into memory, and injects short-reply voice
guidance into prompt context. The WebUI now logs voice lifecycle events, stops
audio when the user starts speaking, and exposes voice conversation state in the
snapshot.

## Phase 89 - Mobile Companion UI

Polish mobile layout for chat, approvals, notifications, and mission status.

Progress: added `core.mobile_companion`, which produces mobile status text,
runtime badges, and compact tab metadata from Personal OS, missions, memory,
files, approvals, and notifications. The WebUI now has a fixed mobile companion
dock, mobile status pill, runtime badge sync, and responsive CSS that hides the
desktop sidebar on small screens so chat, approvals, notifications, and mission
status stay usable.

## Phase 90 - Offline Local Mode

Prefer local models/tools when cloud access is down or the user requests
private mode.

Progress: added `core.offline_mode`, which detects private/offline/local-only
requests, watches provider health for degraded cloud routes, recommends Ollama
local routing, and injects local-first constraints into prompt context. WebUI
prompt handling now emits an offline-mode event and sets the active route to the
local provider/model when local mode is preferred, while Settings shows offline
state, trigger terms, host, and constraints.

## Phase 91 - Safety Incident Log

Record blocked actions, dangerous prompts, secret detections, and approval
denials for review.

Progress: added `core.safety_incidents`, which records secret-looking prompts,
dangerous operation requests, denied approvals, blocked actions, and policy
events into a durable per-project safety log. WebUI prompt handling now logs
incidents passively, approval denials create incident records, Settings shows
open/critical incident counts, and prompt context warns Crypt not to blindly
retry blocked or denied actions.

## Phase 92 - Evaluation Harness Expansion

Grade autonomous tasks beyond code: business, research, memory, browser, voice,
and WebUI stability.

Progress: added `core.eval_harness`, an expanded scenario/rubric layer for
business autopilot, research source quality, memory self-improvement, browser
visual QA, voice conversation, and WebUI stability. It scores runtime snapshots,
can write reports, surfaces scenario scores in Settings, and injects evaluation
status into prompt context so Crypt can see which autonomous capabilities need
evidence.

## Phase 93 - Recovery And Repair Doctor

Detect broken setup, missing voice assets, failed auth, bad config, and stale
WebUI state with repair commands.

Progress: added `core.repair_doctor`, a structured recovery layer that checks
app/workspace writeability, provider/model config, active provider health,
Kokoro voice assets, offline fallback readiness, stale job queue state, and live
replay attachment. It returns concrete repair commands, surfaces failing checks
in Settings, feeds prompt context so Crypt can repair before retrying broken
paths, and extends the CLI doctor report with actionable fixes.

## Phase 94 - Plugin/Connector Readiness Layer

Represent external connectors, required auth, scopes, and safe actions before
Crypt tries to use them.

Progress: added `core.connector_readiness`, which maps GitHub, email,
calendar, storage, Slack, Discord, Reddit, Stripe, analytics, and database
connectors into readiness cards with required auth, scopes, safe read/draft
actions, approval-only actions, blocked actions, and setup guidance. WebUI
Settings now shows connector readiness, and prompt context tells Crypt to
draft/read first, create credential references instead of asking for raw
secrets, and request explicit approval before external writes, sends, posts, or
payment actions.

## Phase 95 - Autonomous Daily Brief

Summarize overnight changes, open missions, approvals, reminders, and suggested
next actions.

Progress: added `core.daily_brief`, which builds a durable daily summary from
notifications, job queue changes, live replay, monitors, open work threads,
goals, scheduled follow-ups, credential references, connector readiness, and
repair doctor output. It can write markdown/latest JSON reports, surfaces next
actions in Settings, and injects urgent approvals, reminders, and repair steps
into prompt context so Crypt starts each session oriented without asking the
user to orchestrate.

## Phase 96 - Long-Running Mission Workers

Let durable missions run background cycles with state, logs, and explicit
external-action gates.

Progress: added `core.mission_workers`, a persistent worker layer for durable
missions with active/blocked/paused/completed state, cycle logs, cadence,
queued background jobs, thread/goal links, and explicit external-action gates.
Workers can run due cycles into the job queue, pause/complete, require approval
before posts/sends/payments/writes, and resume after approval. Settings now
shows active/gated workers, and prompt context includes worker status so Crypt
can continue long-running missions without making the user manage the board.

## Phase 97 - User Trust Calibration

Learn how much initiative the user wants per domain and adjust questions versus
execution.

Progress: added `core.trust_calibration`, a per-domain initiative profile for
code, UI, business, research, memory, personal, external, finance, and system
work. It passively records autonomy/caution signals from chat, adjusts
execute/draft/ask guidance, keeps external and finance work approval-gated, and
surfaces the trust profile in Settings. WebUI prompt handling now uses the trust
decision to reduce unnecessary clarification for trusted low-risk work while
asking or drafting when the domain/risk says to slow down.

## Phase 98 - Productized Onboarding

Replace prompts with a one-screen setup that configures voice, providers,
autonomy, memory, remote access, and safety.

## Phase 99 - Full-System Chaos Checks

Run simulated failures for provider outage, broken tools, corrupt memory, bad
config, and stale WebUI sessions.

## Phase 100 - Crypt 1.0 Release Candidate

Generate the final release checklist, benchmark report, screenshots, upgrade
notes, known risks, rollback plan, and push/PR package.
