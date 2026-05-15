const state = {
  seq: 0,
  busy: false,
  activeApproval: null,
  activityOpen: false,
  currentView: "chat",
  snapshot: null,
  events: [],
  messages: [],
  sessions: [],
  currentSessionId: "",
  taskSessions: {},
  liveTurns: {},
  messageSeq: 0,
  animationStarted: false,
  shellKeys: {
    engine: "",
    providers: "",
    sessions: "",
    core: "",
    agents: "",
  },
  engine: {
    provider: "",
    model: "",
    route: "",
    agentId: "",
  },
  composer: {
    advanced: localStorage.getItem("crypt.composer.advanced") === "1",
  },
  voice: {
    recognition: null,
    desired: false,
    listening: false,
    manuallyStopping: false,
    restartAttempts: 0,
    restartTimer: 0,
    interim: "",
    supported: null,
  },
  voiceOut: {
    enabled: localStorage.getItem("crypt.voice.output.enabled") === "1",
    voice: localStorage.getItem("crypt.voice.output.voice") || "af_heart",
    speed: Number(localStorage.getItem("crypt.voice.output.speed") || "0.96"),
    audio: null,
    busy: false,
    speakToken: 0,
  },
  poll: {
    eventsStarted: false,
    snapshotStarted: false,
  },
  liveTimers: {},
};

const CHAT_STORE_KEY = "crypt.webui.chatSessions.v2";
const MAX_STORED_SESSIONS = 30;
const MAX_SESSION_MESSAGES = 200;
const STICKY_SCROLL_PX = 96;

const viewMeta = {
  panel: ["Home", "Command Center"],
  chat: ["Chat", "Crypt"],
  files: ["Files", "Workspace Files"],
  terminal: ["Terminal", "Command Surface"],
  jobs: ["Jobs", "Runtime Work"],
  missions: ["Missions", "Autonomous Follow-Through"],
  agents: ["Agents", "Specialists"],
  memory: ["Memory", "Durable Memory"],
  skills: ["Skills", "Skill Library"],
  persona: ["Persona", "Crypt Soul"],
  models: ["Models", "Model Routes"],
  providers: ["Providers", "Provider Access"],
  tools: ["Tools", "Tool Arsenal"],
  gateway: ["Gateway", "Local Gateway"],
  settings: ["Settings", "Runtime Settings"],
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function oneLine(value, limit = 140) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit - 1).trim()}...` : text;
}

function textFrom(event) {
  if (event.text) return String(event.text);
  if (event.error) return String(event.error);
  if (event.snapshot) return `${event.snapshot.provider} / ${event.snapshot.model}`;
  if (event.prompt) return String(event.prompt);
  return JSON.stringify(event, null, 2);
}

function toolResultSummary(event) {
  if (event.ok === false) {
    return oneLine(event.error || event.text || textFrom(event), 140);
  }
  const tool = friendlyToolName(event.tool);
  if (event.text && /schema validation failed|read-before-edit|PermissionError|Traceback|failed/i.test(event.text)) {
    return oneLine(event.text, 140);
  }
  return `${tool} completed.`;
}

function stableJson(value) {
  return JSON.stringify(value ?? null);
}

function setText(selector, text) {
  const node = $(selector);
  if (node && node.textContent !== String(text)) node.textContent = String(text);
}

async function json(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function setStatus(text) {
  $("#sideStatus").textContent = text;
}

function newSessionId() {
  if (window.crypto?.randomUUID) return `web-${window.crypto.randomUUID()}`;
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function loadChatSessions() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CHAT_STORE_KEY) || "[]");
    state.sessions = Array.isArray(parsed)
      ? parsed.filter((item) => item && item.id).slice(0, MAX_STORED_SESSIONS)
      : [];
  } catch (error) {
    state.sessions = [];
  }
  if (!state.sessions.length) {
    state.sessions.push(emptySession());
  }
  state.currentSessionId = state.sessions[0].id;
  hydrateCurrentSession();
  saveChatSessions();
}

function emptySession() {
  const now = Date.now();
  return {
    id: newSessionId(),
    title: "New conversation",
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
}

function currentSession() {
  let session = state.sessions.find((item) => item.id === state.currentSessionId);
  if (!session) {
    session = state.sessions[0] || emptySession();
    state.currentSessionId = session.id;
    if (!state.sessions.length) state.sessions.push(session);
  }
  return session;
}

function hydrateCurrentSession() {
  state.messages = (currentSession().messages || []).map((message) => ({
    ...message,
    live: Array.isArray(message.live) ? message.live.slice(-10) : [],
    typing: false,
  }));
}

function saveChatSessions() {
  try {
    localStorage.setItem(CHAT_STORE_KEY, JSON.stringify(state.sessions.slice(0, MAX_STORED_SESSIONS)));
  } catch (error) {
    addActivity("Sessions", "Could not save browser chat sessions.");
  }
}

function persistCurrentSession(renderList = true) {
  const session = currentSession();
  session.messages = state.messages
    .slice(-MAX_SESSION_MESSAGES)
    .map(({ role, label, text, id, uiId, live }) => ({
      role,
      label,
      text,
      id,
      uiId,
      live: Array.isArray(live) ? live.slice(-10) : [],
    }));
  session.updatedAt = Date.now();
  const firstUser = session.messages.find((message) => message.role === "user" && message.text);
  if (firstUser) session.title = oneLine(firstUser.text, 54);
  state.sessions = [session, ...state.sessions.filter((item) => item.id !== session.id)].slice(0, MAX_STORED_SESSIONS);
  saveChatSessions();
  if (renderList) renderSessionList();
}

function createChatSession() {
  const session = emptySession();
  state.sessions = [session, ...state.sessions.filter((item) => item.messages?.length || item.id === state.currentSessionId)]
    .slice(0, MAX_STORED_SESSIONS);
  state.currentSessionId = session.id;
  state.messages = [];
  saveChatSessions();
  renderSessionList();
}

function switchChatSession(sessionId) {
  if (!sessionId || sessionId === state.currentSessionId) return;
  persistCurrentSession();
  state.currentSessionId = sessionId;
  hydrateCurrentSession();
  renderSessionList();
  setView("chat");
}

function renderSessionList() {
  const list = $("#sessionList");
  if (!list) return;
  setText("#sessionCount", state.sessions.length);
  list.innerHTML = state.sessions
    .slice(0, 8)
    .map((session) => `
      <button class="mini-item session-item${session.id === state.currentSessionId ? " active" : ""}" type="button" data-session-id="${escapeHtml(session.id)}">
        <b>${escapeHtml(session.title || "New conversation")}</b>
        <span>${escapeHtml((session.messages || []).length)} msgs / ${escapeHtml(relativeTime(session.updatedAt))}</span>
      </button>
    `)
    .join("");
}

function relativeTime(ts) {
  const delta = Math.max(0, Date.now() - Number(ts || Date.now()));
  const min = Math.floor(delta / 60000);
  if (min < 1) return "now";
  if (min < 60) return `${min}m ago`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function reviewTime(ts) {
  const value = Number(ts || 0);
  if (!value) return "";
  const delta = value - Date.now();
  const abs = Math.abs(delta);
  const min = Math.floor(abs / 60000);
  const label = min < 1
    ? "now"
    : min < 60
      ? `${min}m`
      : Math.floor(min / 60) < 24
        ? `${Math.floor(min / 60)}h`
        : `${Math.floor(min / 1440)}d`;
  return delta > 0 ? `in ${label}` : `${label} late`;
}

function renderShell(snapshot = state.snapshot) {
  if (!snapshot) return;
  const engineText = `${providerLabel(snapshot.provider || "crypt", snapshot)} / ${modelLabel(snapshot.model || "auto", snapshot)}`;
  setText("#enginePill", engineText);
  renderSessionList();
  syncEngineControls(snapshot);
  syncAgentControl(snapshot);
  syncVoiceOutputControls(snapshot);

  const coreKey = stableJson(snapshot.coreFeatures || []);
  if (coreKey !== state.shellKeys.core) {
    state.shellKeys.core = coreKey;
    renderCoreFeatures(snapshot.coreFeatures || []);
  }
}

function renderCoreFeatures(features) {
  const container = $("#quietStats");
  container.innerHTML = "";
  for (const feature of features || []) {
    const card = document.createElement("article");
    card.className = "core-card";
    card.dataset.feature = feature.id || "";
    card.classList.toggle("active", feature.id === state.currentView);
    card.title = feature.detail || "";
    card.innerHTML = `
      <div class="core-card-top">
        <span class="core-label">${escapeHtml(feature.label || feature.id || "Core")}</span>
        <b>${escapeHtml(feature.value ?? "")}</b>
      </div>
      <span class="core-status">${escapeHtml(feature.status || "")}</span>
      <p>${escapeHtml(feature.detail || "")}</p>
    `;
    container.appendChild(card);
  }
}

function providerRows(snapshot = state.snapshot) {
  return (snapshot?.providers || []).filter((provider) => provider && provider.id);
}

function modelsFor(providerId, snapshot = state.snapshot) {
  const provider = providerRows(snapshot).find((item) => item.id === providerId);
  return provider ? provider.models || [] : [];
}

function optionMarkup(options, selected) {
  return options.map((option) => {
    const value = typeof option === "string" ? option : option.value;
    const label = typeof option === "string" ? option : option.label;
    return `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`;
  }).join("");
}

function modelMetadata(model, snapshot = state.snapshot) {
  const raw = String(model || "");
  const providers = providerRows(snapshot);
  for (const provider of providers) {
    const found = (provider.modelMetadata || []).find((item) => item.id === raw);
    if (found) return found;
  }
  return null;
}

function modelLabel(model, snapshot = state.snapshot) {
  const raw = String(model || "");
  const meta = modelMetadata(raw, snapshot);
  if (meta?.label) return meta.label;
  const labels = {
    "crypt-pro": "ChatGPT 5 Codex",
    "crypt-max": "ChatGPT 5.5",
    "crypt-balanced": "ChatGPT 5.4",
    "crypt-fast": "ChatGPT 5.4 Mini",
    "crypt-legacy": "ChatGPT 5.3 Codex",
    "crypt-spark": "ChatGPT 5.3 Spark",
    "crypt-mini": "Codex Mini",
    "gpt-5-codex": "ChatGPT 5 Codex",
    "gpt-5.3-codex": "ChatGPT 5.3 Codex",
    "gpt-5.3-codex-spark": "ChatGPT 5.3 Spark",
    "gpt-5.4-mini": "ChatGPT 5.4 Mini",
    "gpt-5.4": "ChatGPT 5.4",
    "gpt-5.5": "ChatGPT 5.5",
  };
  if (labels[raw]) return labels[raw];
  return raw
    .replace(/:cloud$/i, " Cloud")
    .replace(/[-_:]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .replace(/\bGpt\b/g, "GPT")
    .replace(/\bUi\b/g, "UI");
}

function routeLabel(role) {
  return {
    planner: "Think",
    builder: "Build",
    reviewer: "Review",
    fast: "Fast",
    fallback: "Fallback",
  }[role] || oneLine(role || "Route", 24);
}

function providerLabel(providerId, snapshot = state.snapshot) {
  const provider = providerRows(snapshot).find((item) => item.id === providerId);
  return provider?.label || providerId || "Provider";
}

function modelOptionMarkup(options, selected) {
  return options.map((value) => (
    `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(modelLabel(value))}</option>`
  )).join("");
}

function syncEngineControls(snapshot = state.snapshot) {
  const providerSelect = $("#providerSelect");
  const modelSelect = $("#modelSelect");
  const routeSelect = $("#routeSelect");
  if (!providerSelect || !modelSelect || !snapshot) return;

  const provider = snapshot.provider || state.engine.provider || "crypt";
  const model = snapshot.model || state.engine.model || "";
  state.engine.provider = provider;
  state.engine.model = model;

  const providers = providerRows(snapshot).map((item) => ({ value: item.id, label: item.label || item.id }));
  const providerKey = stableJson({ providers, provider });
  if (providerKey !== state.shellKeys.providers) {
    state.shellKeys.providers = providerKey;
    providerSelect.innerHTML = optionMarkup(providers, provider);
  }

  const models = modelsFor(provider, snapshot);
  const modelOptions = models.includes(model) || !model ? models : [model, ...models];
  const modelKey = stableJson({ provider, models: modelOptions, model });
  if (modelKey !== state.shellKeys.engine) {
    state.shellKeys.engine = modelKey;
    modelSelect.innerHTML = modelOptionMarkup(modelOptions, model);
  }

  if (routeSelect) routeSelect.value = state.engine.route || "auto";
}

function syncAgentControl(snapshot = state.snapshot) {
  const select = $("#agentSelect");
  if (!select || !snapshot) return;
  const agents = snapshot.agentProfiles || [];
  const options = agents.length
    ? [{ value: "", label: "Crypt decides" }, ...agents.map((agent) => ({ value: agent.id, label: agent.name }))]
    : [{ value: "", label: "No saved agents" }];
  if (state.engine.agentId && !agents.some((agent) => agent.id === state.engine.agentId)) {
    state.engine.agentId = "";
  }
  const key = stableJson({ options, selected: state.engine.agentId });
  if (key !== state.shellKeys.agents) {
    state.shellKeys.agents = key;
    select.innerHTML = optionMarkup(options, state.engine.agentId);
  }
}

function syncVoiceOutputControls(snapshot = state.snapshot) {
  const voiceStatus = snapshot?.voice || {};
  const ready = Boolean(voiceStatus.ready);
  const voices = voiceStatus.voices || [];
  const select = $("#ttsVoiceSelect");
  const toggle = $("#ttsToggle");
  const test = $("#ttsTestButton");
  const status = $("#ttsStatus");

  if (select) {
    const options = voices.length
      ? voices.map((voice) => ({
          value: voice.id,
          label: `${voice.label || voice.id} ${voice.accent || ""}${voice.style ? ` - ${voice.style}` : ""}`.trim(),
        }))
      : [{ value: state.voiceOut.voice, label: "Kokoro" }];
    const selected = voices.some((voice) => voice.id === state.voiceOut.voice)
      ? state.voiceOut.voice
      : (voiceStatus.default_voice || "af_heart");
    state.voiceOut.voice = selected;
    const key = stableJson({ options, selected });
    if (select.dataset.key !== key) {
      select.dataset.key = key;
      select.innerHTML = optionMarkup(options, selected);
    }
    select.value = selected;
    select.disabled = !ready;
  }
  if (toggle) {
    toggle.disabled = !ready;
    toggle.classList.toggle("active", ready && state.voiceOut.enabled);
    toggle.setAttribute("aria-pressed", String(ready && state.voiceOut.enabled));
    toggle.textContent = state.voiceOut.enabled ? "Speak on" : "Speak off";
  }
  if (test) {
    test.disabled = !ready || state.voiceOut.busy;
    test.textContent = state.voiceOut.busy ? "Voice..." : "Test";
  }
  if (status && !state.voiceOut.busy) {
    const missing = voiceStatus.missing || [];
    status.textContent = ready ? "kokoro ready" : `kokoro setup needed${missing.length ? `: ${missing[0]}` : ""}`;
  }
}

function setView(view) {
  state.currentView = viewMeta[view] ? view : "panel";
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === state.currentView);
  });
  const [eyebrow, title] = viewMeta[state.currentView];
  $("#viewEyebrow").textContent = eyebrow;
  $("#viewTitle").textContent = title;
  renderCurrentView();
}

function engineName(snapshot = state.snapshot) {
  return `${providerLabel(snapshot?.provider || "crypt", snapshot)} / ${modelLabel(snapshot?.model || "auto")}`;
}

function renderCurrentView() {
  const snapshot = state.snapshot || {};
  const host = $("#viewHost");
  const [eyebrow, title] = viewMeta[state.currentView] || viewMeta.panel;
  $("#viewEyebrow").textContent = eyebrow;
  $("#viewTitle").textContent = title;
  if (state.currentView === "panel") host.innerHTML = panelView(snapshot);
  else if (state.currentView === "chat") host.innerHTML = chatView();
  else if (state.currentView === "files") host.innerHTML = filesView(snapshot);
  else if (state.currentView === "terminal") host.innerHTML = terminalView(snapshot);
  else if (state.currentView === "jobs") host.innerHTML = jobsView(snapshot);
  else if (state.currentView === "missions") host.innerHTML = missionsView(snapshot);
  else if (state.currentView === "agents") host.innerHTML = agentsView(snapshot);
  else if (state.currentView === "memory") host.innerHTML = memoryView(snapshot);
  else if (state.currentView === "skills") host.innerHTML = skillsView(snapshot);
  else if (state.currentView === "persona") host.innerHTML = personaView(snapshot);
  else if (state.currentView === "models") host.innerHTML = modelsView(snapshot);
  else if (state.currentView === "providers") host.innerHTML = providersView(snapshot);
  else if (state.currentView === "tools") host.innerHTML = toolsView(snapshot);
  else if (state.currentView === "gateway") host.innerHTML = gatewayView(snapshot);
  else host.innerHTML = settingsView(snapshot);
  attachViewHandlers();
  if (state.currentView === "chat") scrollFeed();
}

function panelView(snapshot) {
  const features = snapshot.coreFeatures || [];
  const matrix = snapshot.capabilityMatrix || {};
  const capabilities = matrix.capabilities || [];
  const lookup = Object.fromEntries(features.map((feature) => [feature.id, feature]));
  const journal = snapshot.memoryJournal || {};
  const threads = snapshot.workThreads || [];
  const activeThreads = threads.filter((thread) => !["completed", "cancelled"].includes(thread.state || "active"));
  const blocked = activeThreads.filter((thread) => (thread.state || "active") === "blocked");
  const active = [
    ["Engine", engineName(snapshot), "Model and provider currently behind chat."],
    ["Threads", activeThreads.length, blocked.length ? `${blocked.length} blocked approval item(s)` : "No blocked work."],
    ["Memory", `${journal.longTermCount || 0} long-term`, `${journal.openLoopCount || 0} open loop(s).`],
    ["Agents", (snapshot.agentProfiles || []).length, "Saved specialists Crypt can reuse."],
    ["Capabilities", `${matrix.ready || 0}/${matrix.total || 0} ready`, matrix.needsSetup ? `${matrix.needsSetup} need setup.` : "Runtime map is clean."],
  ];
  const calmCards = ["chat", "plan", "agents", "memory"]
    .map((id) => lookup[id])
    .filter(Boolean);
  const recent = state.sessions.slice(0, 4);
  const nextThreads = activeThreads.slice(0, 4);
  return `
    <section class="home-grid">
      <article class="home-hero">
        <span class="eyebrow">Crypt is live</span>
        <h3>No dashboard homework.</h3>
        <p>Talk normally. Crypt keeps the memory, missions, tools, agents, and follow-through under the hood.</p>
        <div class="home-signal" aria-hidden="true">
          <i></i><i></i><i></i>
        </div>
      </article>
      <aside class="home-stack">
        ${active.map(([label, value, detail]) => statCard(label, value, detail)).join("")}
      </aside>
    </section>
    <section class="home-ledger">
      <div class="panel-card">
        <h3>Next Moves</h3>
        <div class="compact-list">
          ${nextThreads.map((thread) => compactItem(thread.state || "active", thread.title, thread.next_action || "Crypt will choose the next safe step.")).join("") || compactItem("idle", "No active work threads", "Say the outcome in chat and Crypt will create one.")}
        </div>
      </div>
      <div class="panel-card">
        <h3>Recent Chats</h3>
        <div class="compact-list">
          ${recent.map((session) => compactItem(`${(session.messages || []).length} msgs`, session.title || "New conversation", relativeTime(session.updatedAt))).join("")}
        </div>
      </div>
      <div class="panel-card wide">
        <h3>Capability Matrix</h3>
        <div class="compact-list">
          ${capabilities.slice(0, 6).map((capability) => compactItem(capability.status || "watch", capability.label, capability.evidence || capability.summary)).join("") || compactItem("empty", "No capability snapshot yet", "Refresh once the runtime is ready.")}
        </div>
      </div>
    </section>
    <section class="feature-grid calm-grid home-capabilities">
      ${calmCards.map((feature) => featureCard(feature)).join("")}
    </section>
  `;
}

function chatView() {
  return `
    <section class="chat-view">
      <div id="feed" class="feed" aria-live="polite">
        ${state.messages.map(messageMarkup).join("") || `
          <article class="empty-chat">
            <p>Crypt</p>
            <h3>Say it.</h3>
            <span>I will figure out the route, tools, memory, and agents. No ceremony.</span>
          </article>
        `}
      </div>
    </section>
  `;
}

function filesView(snapshot) {
  const project = snapshot.project || {};
  const files = snapshot.filesPreview || [];
  const artifacts = snapshot.artifactsPreview || [];
  const groups = snapshot.artifactGroups || [];
  const summary = snapshot.artifactSummary || {};
  const latest = artifacts[0];
  return `
    <section class="two-col">
      <div class="panel-card wide artifact-studio-hero">
        <span class="eyebrow">Artifact Studio</span>
        <h3>Every file Crypt makes gets a trail.</h3>
        <p>${escapeHtml(latest ? `${latest.name || latest.rel_path} - ${oneLine(latest.preview || latest.provenance || "ready", 160)}` : "Generated sites, docs, reports, scripts, and screenshots will land here with mission context and status.")}</p>
        <div class="pill-row">
          ${(project.languages || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
          ${(project.frameworks || []).slice(0, 5).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
        </div>
      </div>
      <div class="panel-card">
        <h3>Output State</h3>
        ${statCard("Artifacts", summary.total || artifacts.length || 0)}
        ${statCard("Mission linked", summary.missionLinked || 0)}
        ${statCard("Verified", summary.verified || 0)}
      </div>
    </section>
    <section class="artifact-grid">
      ${groups.map(artifactGroupMarkup).join("") || emptyArtifactStudio()}
    </section>
    <section class="data-list workspace-file-list">
      ${files.map((file) => row(file.kind === "dir" ? "Folder" : "File", file.name, file.path)).join("") || emptyRow("No files listed")}
    </section>
  `;
}

function artifactGroupMarkup(group) {
  const artifacts = group.artifacts || [];
  return `
    <article class="artifact-group">
      <header>
        <span>${escapeHtml(group.status || "workspace")}</span>
        <b>${escapeHtml(group.title || "Workspace artifacts")}</b>
        <em>${escapeHtml(`${group.count || artifacts.length || 0} file${(group.count || artifacts.length || 0) === 1 ? "" : "s"}`)}</em>
      </header>
      <div class="artifact-items">
        ${artifacts.map(artifactRowMarkup).join("") || `<p>No artifacts attached yet.</p>`}
      </div>
    </article>
  `;
}

function artifactRowMarkup(artifact) {
  const updated = Number(artifact.updated_at || 0) ? reviewTime(Number(artifact.updated_at) * 1000) : "new";
  const detail = artifact.provenance || artifact.source || updated;
  return `
    <div class="artifact-item">
      <span>${escapeHtml(artifact.kind || "file")}</span>
      <b>${escapeHtml(oneLine(artifact.name || artifact.rel_path || "artifact", 80))}</b>
      <p>${escapeHtml(oneLine(artifact.preview || detail, 180))}</p>
      <em>${escapeHtml(artifact.status || "ready")}</em>
    </div>
  `;
}

function emptyArtifactStudio() {
  return `
    <article class="artifact-group empty-artifacts">
      <header>
        <span>ready</span>
        <b>No generated artifacts yet</b>
        <em>0 files</em>
      </header>
      <div class="artifact-items">
        <p>Ask Crypt to build a site, write a report, make a script, or create a tracker. The output will be indexed here automatically.</p>
      </div>
    </article>
  `;
}

function terminalView(snapshot) {
  return `
    <section class="two-col">
      <div class="panel-card wide">
        <h3>Command Surface</h3>
        <p>Terminal work runs through Crypt so approvals, logs, and learning stay attached.</p>
        <button class="ask-button primary" data-ask="Run the right verification command for this repo, explain failures, and fix what is safe.">Verify repo</button>
        <button class="ask-button" data-ask="Inspect available commands and tell me the safest way to run this project.">Find commands</button>
      </div>
      <div class="panel-card">
        <h3>Runtime</h3>
        ${statCard("Approval", snapshot.approval || "approval")}
        ${statCard("Thinking", snapshot.thinkingMode || "fast")}
      </div>
    </section>
    <section class="data-list">${(snapshot.toolsPreview || []).slice(0, 10).map((tool) => row("Tool", tool.name, tool.description)).join("")}</section>
  `;
}

function jobsView(snapshot) {
  const events = state.events.slice(-20).reverse();
  const drafts = snapshot.externalDrafts?.drafts || [];
  return `
    <section class="two-col">
      <div class="panel-card">
        <h3>Active Task</h3>
        ${statCard("Status", snapshot.activeTask ? "running" : "idle")}
        ${statCard("Task", snapshot.activeTask || "none")}
      </div>
      <div class="panel-card">
        <h3>Autonomy</h3>
        ${statCard("Cycles", snapshot.autonomyCycles || 0)}
        <button class="small-action" id="runAutonomyButton" type="button">Run cycle</button>
      </div>
      <div class="panel-card wide">
        <h3>External Draft Queue</h3>
        <div class="compact-list">${drafts.slice(0, 5).map((draft) => compactItem(draft.status || "draft", draft.title || draft.kind, draft.target || "approval required before external effect")).join("") || compactItem("clear", "No external drafts waiting", "Posts, emails, purchases, and account actions will queue here.")}</div>
      </div>
    </section>
    <section class="data-list">${events.map((event) => row(event.event || "Event", textFrom(event), new Date((event.ts || 0) * 1000).toLocaleTimeString())).join("") || emptyRow("No runtime events yet")}</section>
  `;
}

function missionsView(snapshot) {
  const goals = snapshot.goals || [];
  const threads = snapshot.workThreads || [];
  const active = goals.filter((goal) => (goal.status || "active") === "active");
  const watched = goals.filter((goal) => goal.cadence);
  const due = watched.filter((goal) => Number(goal.next_review_at || 0) * 1000 <= Date.now());
  const blockedThreads = threads.filter((thread) => (thread.state || "active") === "blocked");
  return `
    <section class="mission-board">
      <div class="panel-card mission-hero">
        <span class="eyebrow">Mission brain</span>
        <h3>Saved goals become work threads.</h3>
        <p>Crypt creates these from normal chat when something needs follow-through. Each thread keeps the state, next action, blockers, cadence, and due date.</p>
        <button class="small-action" id="runAutonomyButton" type="button">Review now</button>
      </div>
      <div class="mission-metrics">
        ${statCard("Goals", active.length)}
        ${statCard("Threads", threads.length)}
        ${statCard("Blocked", blockedThreads.length)}
        ${statCard("Due", due.length)}
      </div>
    </section>
    <section class="data-list mission-list thread-list">${threads.map(threadRow).join("") || emptyRow("No work threads yet")}</section>
    <section class="data-list mission-list">${goals.map(missionRow).join("") || emptyRow("No missions yet")}</section>
  `;
}

function missionRow(goal) {
  const cadence = goal.cadence ? `${goal.cadence} review` : "as needed";
  const next = Number(goal.next_review_at || 0)
    ? `next ${reviewTime(Number(goal.next_review_at) * 1000)}`
    : goal.goal_id;
  return `
    <article class="data-row mission-row">
      <span>${escapeHtml(goal.status || "active")}</span>
      <b>${escapeHtml(goal.title || "Untitled mission")}</b>
      <p>${escapeHtml(goal.success_metric || cadence)} - ${escapeHtml(next)}</p>
    </article>
  `;
}

function threadRow(thread) {
  const blockers = (thread.blockers || []).join(" ");
  const pending = (thread.tasks || []).find((task) => task.status !== "done");
  const metric = (thread.success_metrics || [])[0] || "";
  const detail = blockers || pending?.title || thread.next_action || metric || "Crypt will pick the next safe step.";
  const metricText = metric && metric !== detail ? ` metric: ${metric}` : "";
  const due = Number(thread.due_at || 0) ? `due ${reviewTime(Number(thread.due_at) * 1000)}` : "as needed";
  return `
    <article class="data-row mission-row work-thread-row">
      <span>${escapeHtml(thread.state || "active")}</span>
      <b>${escapeHtml(thread.title || "Untitled thread")}</b>
      <p>${escapeHtml(`${due} - ${detail}${metricText}`)}</p>
    </article>
  `;
}

function agentsView(snapshot) {
  const agents = snapshot.agentProfiles || [];
  const definitions = snapshot.agentDefinitions || [];
  const provider = state.engine.provider || snapshot.provider || "crypt";
  const model = state.engine.model || snapshot.model || "";
  const providerOptions = providerRows(snapshot).map((item) => ({ value: item.id, label: item.label || item.id }));
  const modelOptions = modelsFor(provider, snapshot);
  const safeModels = modelOptions.includes(model) || !model ? modelOptions : [model, ...modelOptions];
  return `
    <section class="two-col">
      <form id="agentForm" class="panel-card form-card wide agent-form">
        <h3>Save A Specialist</h3>
        <p>Create the agent once. Crypt can route matching work through that role instead of making you manage it every time.</p>
        <div class="form-grid">
          <input name="name" placeholder="Agent name: growth operator, UI killer, finance tracker...">
          <select name="agentType">
            ${definitions.map((definition) => `<option value="${escapeHtml(definition.name)}">${escapeHtml(definition.label || definition.name)}</option>`).join("")}
          </select>
          <select name="provider" id="agentProviderSelect">
            ${optionMarkup(providerOptions, provider)}
          </select>
          <select name="model" id="agentModelSelect">
            ${modelOptionMarkup(safeModels, model)}
          </select>
        </div>
        <textarea name="purpose" rows="3" placeholder="What should this agent own? Example: find customers, write launch copy, monitor income, ship site changes."></textarea>
        <button type="submit">Save agent</button>
      </form>
      <div class="panel-card">
        <h3>How Crypt Uses Them</h3>
        <p>Saved agents also update the matching runtime route, so delegated work uses the provider and model you chose.</p>
        <button class="ask-button" data-ask="Look at my saved agents and tell me which specialists you would create next.">Suggest agents</button>
      </div>
    </section>
    <section class="feature-grid agent-grid">
      ${agents.map((agent) => featureCard({
        label: agent.name,
        value: agent.model,
        status: `${agent.agent_type} / ${agent.provider}`,
        detail: `${agent.purpose} Route: ${agent.route_role}`,
      })).join("") || emptyRow("No saved agents yet")}
    </section>
  `;
}

function memoryView(snapshot) {
  const lessons = snapshot.lessonsPreview || [];
  const journal = snapshot.memoryJournal || {};
  const entities = snapshot.entitiesPreview || {};
  const businessEntities = snapshot.businessEntities || {};
  const graph = snapshot.knowledgeGraph || {};
  const entityRows = entities.preview || [];
  const businessRows = businessEntities.preview || [];
  const longTerm = journal.longTermPreview || [];
  const working = journal.workingPreview || [];
  const loops = journal.openLoopPreview || [];
  return `
    <section class="two-col">
      <div class="panel-card wide">
        <h3>Self-Updating Memory</h3>
        <p>Crypt watches normal conversation, promotes useful signals, keeps a rolling short-term scratchpad, and writes the durable version into Markdown.</p>
        <button class="ask-button primary" data-ask="Audit my current memory, remove weak assumptions, and tell me what you will remember going forward.">Audit memory</button>
      </div>
      <div class="panel-card">
        <h3>Memory</h3>
        ${statCard("Long-term", journal.longTermCount || 0)}
        ${statCard("Open loops", journal.openLoopCount || 0)}
        ${statCard("Entities", entities.count || 0)}
        ${statCard("Business", businessEntities.count || 0)}
        ${statCard("Graph", `${graph.nodeCount || 0}/${graph.edgeCount || 0}`)}
        ${statCard("Lessons", snapshot.lessons || 0)}
      </div>
    </section>
    <section class="data-list">${businessRows.map(businessEntityRow).join("") || ""}</section>
    <section class="data-list">${entityRows.map(entityRow).join("") || ""}</section>
    <section class="data-list">${longTerm.map(memorySignalRow).join("") || emptyRow("No long-term journal memory yet")}</section>
    <section class="data-list">${loops.map(memorySignalRow).join("") || ""}</section>
    <section class="data-list">${working.map(memorySignalRow).join("") || ""}</section>
    <section class="data-list">${lessons.map((lesson) => row("Lesson", lesson.text, `${lesson.scope} / ${lesson.confidence}`)).join("") || emptyRow("No durable memory yet")}</section>
  `;
}

function businessEntityRow(item) {
  const value = Number(item.value || 0) ? `${item.currency || "USD"} ${Number(item.value || 0).toFixed(2)}` : "";
  const detail = [item.status || "active", value, (item.tags || []).slice(0, 3).join(" / ")].filter(Boolean).join(" / ");
  return row(item.kind || "business", item.name || "", detail);
}

function memorySignalRow(item) {
  const label = item.category || "memory";
  const detail = `${(item.tags || []).join(" / ") || item.source || "journal"}${item.hits > 1 ? ` / hits ${item.hits}` : ""}`;
  return row(label, item.text || "", detail);
}

function entityRow(item) {
  const detailParts = [
    item.mentions ? `${item.mentions} mention(s)` : "",
    (item.tags || []).slice(0, 3).join(" / "),
    item.details?.platform || item.details?.relationship || "",
  ].filter(Boolean);
  return row(item.kind || "entity", item.name || "", detailParts.join(" / "));
}

function skillsView(snapshot) {
  const skills = snapshot.skillsPreview || [];
  const frontendSkill = skills.find((skill) => skill.name === "frontend-design");
  return `
    <section class="two-col">
      <form id="forgeForm" class="panel-card form-card">
        <h3>Autoforge Skill</h3>
        <p>Crypt can promote repeated lessons into local SKILL.md files. The UI updates as soon as the skill appears.</p>
        <input name="topic" placeholder="Topic from repeated lessons">
        <button type="submit">Create</button>
      </form>
      <div class="panel-card">
        <h3>Built-In Craft</h3>
        <p>${frontendSkill ? "Frontend design is installed for high-end UI work." : "Frontend design skill is not visible yet."}</p>
        <button class="ask-button" data-ask="Find useful skills for what I am trying to do, learn them, and integrate the ones that fit.">Find skills</button>
        <button class="ask-button" data-ask="Inspect my current skills and suggest what Crypt should learn next.">Audit skills</button>
      </div>
    </section>
    <section class="feature-grid">${skills.map((skill) => featureCard({ label: skill.name, value: skill.enabled ? "on" : "blocked", status: skill.title || "skill", detail: skill.description || skill.path })).join("") || emptyRow("No skills discovered")}</section>
  `;
}

function personaView(snapshot) {
  return `
    <section class="two-col">
      <div class="panel-card wide">
        <h3>Self-Shaping Persona</h3>
        <p>Crypt evolves its own working voice from durable memory and feedback. The goal is blunt, useful, and real without pretending to be conscious.</p>
        <button class="ask-button primary" data-ask="Review your current persona and update it from what you have learned about how I want Crypt to act.">Evolve persona</button>
      </div>
      <div class="panel-card">
        <h3>Soul File</h3>
        <p>${escapeHtml(snapshot.soul?.path || "No soul file yet")}</p>
        ${statCard("Status", snapshot.soul?.active ? "active" : "new")}
        ${statCard("Preferences", snapshot.soul?.preferenceCount || 0)}
      </div>
    </section>
  `;
}

function modelsView(snapshot) {
  return `
    <section class="route-board">
      ${(snapshot.routes || []).map((route) => `
        <article class="route-card">
          <span>${escapeHtml(route.status || "route")}</span>
          <h3>${escapeHtml(routeLabel(route.role))}</h3>
          <b>${escapeHtml(modelLabel(route.model))}</b>
          <p>${escapeHtml(providerLabel(route.provider, snapshot))}</p>
        </article>
      `).join("")}
    </section>
  `;
}

function providersView(snapshot) {
  return `
    <section class="feature-grid provider-grid">
      ${(snapshot.providers || []).map((provider) => `
        <article class="feature-card provider-card">
          <div><span>${escapeHtml(provider.status || "")}</span><b>${escapeHtml(provider.label || provider.id)}</b></div>
          <strong>${escapeHtml(provider.id || "")}</strong>
          <p>${escapeHtml(provider.note || "Models")}</p>
          <div class="model-chip-row">
            ${(provider.models || []).slice(0, 5).map((model) => `<em>${escapeHtml(modelLabel(model))}</em>`).join("")}
          </div>
        </article>
      `).join("")}
    </section>
  `;
}

function toolsView(snapshot) {
  return `<section class="data-list">${(snapshot.toolsPreview || []).map((tool) => row("Tool", tool.name, tool.description)).join("")}</section>`;
}

function gatewayView(snapshot) {
  return `
    <section class="two-col">
      <div class="panel-card wide">
        <h3>Local Gateway</h3>
        <p>${escapeHtml(snapshot.webui?.url || "local")}</p>
        <button class="ask-button primary" data-ask="Use this local gateway as my command center and explain what it can do right now.">Explain gateway</button>
      </div>
      <div class="panel-card">
        <h3>Workspace</h3>
        <p>${escapeHtml(snapshot.workspace || "")}</p>
      </div>
    </section>
  `;
}

function settingsView(snapshot) {
  const providers = snapshot.providers || [];
  const routes = snapshot.routes || [];
  const tools = snapshot.toolsPreview || [];
  const contracts = snapshot.autonomyContracts?.profiles || [];
  return `
    <section class="feature-grid">
      ${featureCard({ label: "Engine", value: modelLabel(snapshot.model), status: providerLabel(snapshot.provider, snapshot), detail: "Current model used by chat." })}
      ${featureCard({ label: "Approval", value: snapshot.approval, status: snapshot.approvalMode, detail: "Controls when Crypt asks before tools run." })}
      ${featureCard({ label: "Thinking", value: snapshot.thinkingMode, status: snapshot.reasoningEffort, detail: "Provider reasoning mode." })}
      ${featureCard({ label: "Auth", value: snapshot.authOk ? "ready" : "missing", status: snapshot.auth, detail: snapshot.authMessage || "Provider is usable." })}
      ${featureCard({ label: "Gateway", value: "local", status: "webui", detail: snapshot.webui?.url || "local" })}
      ${featureCard({ label: "Workspace", value: "open", status: "local", detail: snapshot.workspace })}
    </section>
    <section class="settings-grid">
      <div class="panel-card">
        <h3>Routes</h3>
        <div class="compact-list">${routes.map((route) => compactItem(route.status || "route", routeLabel(route.role), `${providerLabel(route.provider, snapshot)} / ${modelLabel(route.model)}`)).join("") || compactItem("none", "No routes configured", "Chat falls back to the main engine.")}</div>
      </div>
      <div class="panel-card">
        <h3>Providers</h3>
        <div class="compact-list">${providers.map((provider) => compactItem(provider.status || "provider", provider.label || provider.id, (provider.models || []).slice(0, 3).map(modelLabel).join(", "))).join("")}</div>
      </div>
      <div class="panel-card wide">
        <h3>Tool Surface</h3>
        <div class="compact-list">${tools.slice(0, 8).map((tool) => compactItem("tool", tool.name, tool.description)).join("")}</div>
      </div>
      <div class="panel-card wide">
        <h3>Autonomy Contracts</h3>
        <div class="compact-list">${contracts.map((contract) => compactItem(contract.autonomy_level || "auto", contract.label, contract.ui_summary || contract.default_action)).join("")}</div>
      </div>
    </section>
  `;
}

function statCard(label, value, detail = "") {
  const text = String(value ?? "");
  const lengthClass = text.length > 14 ? " long" : "";
  return `<article class="stat-card${lengthClass}"><span>${escapeHtml(label)}</span><b>${escapeHtml(text)}</b>${detail ? `<p>${escapeHtml(oneLine(detail, 90))}</p>` : ""}</article>`;
}

function featureCard(feature) {
  return `
    <article class="feature-card">
      <div><span>${escapeHtml(feature.status || "")}</span><b>${escapeHtml(feature.label || "")}</b></div>
      <strong>${escapeHtml(feature.value ?? "")}</strong>
      <p>${escapeHtml(oneLine(feature.detail || "", 180))}</p>
    </article>
  `;
}

function row(kind, title, detail = "") {
  return `
    <article class="data-row">
      <span>${escapeHtml(kind)}</span>
      <b>${escapeHtml(oneLine(title, 110))}</b>
      <p>${escapeHtml(oneLine(detail, 220))}</p>
    </article>
  `;
}

function compactItem(kicker, title, detail = "") {
  return `
    <article class="compact-item">
      <span>${escapeHtml(kicker)}</span>
      <b>${escapeHtml(oneLine(title, 88))}</b>
      <p>${escapeHtml(oneLine(detail, 150))}</p>
    </article>
  `;
}

function emptyRow(text) {
  return `<article class="data-row empty"><b>${escapeHtml(text)}</b><p>Ask Crypt to create it.</p></article>`;
}

function messageMarkup(message) {
  const uiId = ensureMessageId(message);
  return `
    <article class="message ${escapeHtml(message.role)}${message.typing ? " typing" : ""}" data-message-id="${uiId}">
      <span class="message-label">${escapeHtml(message.label || (message.role === "user" ? "You" : "Crypt"))}</span>
      <div class="bubble">${messageTextMarkup(message.text, message.typing)}</div>
      ${liveTimelineMarkup(message.live)}
    </article>
  `;
}

function messageTextMarkup(text, typing = false) {
  const safe = escapeHtml(text || (typing ? "Working on it." : ""));
  return safe
    .replace(/\*\*([^*\n][^*]*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`\n]+?)`/g, "<code>$1</code>");
}

function liveTimelineMarkup(items = []) {
  const live = (items || []).slice(-10);
  if (!live.length) return "";
  return `
    <div class="live-timeline">
      ${live.map(liveLineMarkup).join("")}
    </div>
  `;
}

function liveLineMarkup(item, index = 0) {
  return `
    <div class="live-line ${escapeHtml(item.status || "")}" data-live-key="${escapeHtml(item.key || `${item.kind || "live"}:${index}`)}">
      <span>${escapeHtml(item.kind || "live")}</span>
      <b>${escapeHtml(item.title || "")}</b>
      <em>${escapeHtml(item.body || "")}</em>
    </div>
  `;
}

function attachViewHandlers() {
  document.querySelectorAll(".ask-button").forEach((button) => {
    button.addEventListener("click", () => sendPrompt(button.dataset.ask || button.textContent || ""));
  });
  const lessonForm = $("#lessonForm");
  if (lessonForm) {
    lessonForm.addEventListener("submit", submitLesson);
  }
  const preferenceForm = $("#preferenceForm");
  if (preferenceForm) {
    preferenceForm.addEventListener("submit", submitPreference);
  }
  const forgeForm = $("#forgeForm");
  if (forgeForm) {
    forgeForm.addEventListener("submit", submitForge);
  }
  const agentForm = $("#agentForm");
  if (agentForm) {
    agentForm.addEventListener("submit", submitAgent);
  }
  const agentProvider = $("#agentProviderSelect");
  if (agentProvider) {
    agentProvider.addEventListener("change", syncAgentModelSelect);
  }
  document.querySelectorAll("#runAutonomyButton").forEach((button) => {
    button.addEventListener("click", runAutonomy);
  });
}

function syncAgentModelSelect() {
  const providerSelect = $("#agentProviderSelect");
  const modelSelect = $("#agentModelSelect");
  if (!providerSelect || !modelSelect) return;
  const models = modelsFor(providerSelect.value, state.snapshot);
  modelSelect.innerHTML = modelOptionMarkup(models, models[0] || "");
}

function pushMessage(message) {
  ensureMessageId(message);
  state.messages.push(message);
  if (state.messages.length > MAX_SESSION_MESSAGES) state.messages = state.messages.slice(-MAX_SESSION_MESSAGES);
  persistCurrentSession();
  if (state.currentView === "chat") appendMessageNode(message);
}

function updateAssistantMessage(id, text, { append = false, typing = false } = {}) {
  touchLiveTurn(id, { status: typing ? "running" : "idle" });
  const targetSessionId = state.taskSessions[id];
  if (targetSessionId && targetSessionId !== state.currentSessionId) {
    const session = state.sessions.find((item) => item.id === targetSessionId);
    if (session) {
      const messages = session.messages || [];
      let message = messages.find((item) => item.id === id && item.role === "assistant");
      if (!message) {
        message = { id, role: "assistant", label: "Crypt", text: "", uiId: `stored-${id}` };
        messages.push(message);
      }
      message.text = append ? `${message.text || ""}${text}` : text;
      session.messages = messages.slice(-MAX_SESSION_MESSAGES);
      session.updatedAt = Date.now();
      saveChatSessions();
      if (!typing) renderSessionList();
    }
    return;
  }
  let message = state.messages.find((item) => item.id === id && item.role === "assistant");
  if (!message) {
    message = { id, role: "assistant", label: "Crypt", text: "", typing };
    ensureMessageId(message);
    state.messages.push(message);
  }
  message.text = append ? message.text + text : text;
  message.typing = typing;
  persistCurrentSession(!typing);
  if (state.currentView === "chat") updateMessageNode(message);
}

function ensureMessageId(message) {
  if (!message.uiId) {
    state.messageSeq += 1;
    message.uiId = `msg${state.messageSeq}`;
  }
  return message.uiId;
}

function appendMessageNode(message) {
  const feed = $("#feed");
  if (!feed) return;
  const empty = feed.querySelector(".empty-chat");
  if (empty) empty.remove();
  feed.insertAdjacentHTML("beforeend", messageMarkup(message));
  scrollFeed();
}

function updateMessageNode(message) {
  const feed = $("#feed");
  if (!feed) return;
  const shouldStick = isFeedNearBottom(feed);
  const uiId = ensureMessageId(message);
  const node = feed.querySelector(`[data-message-id="${uiId}"]`);
  if (!node) {
    appendMessageNode(message);
    return;
  }
  const bubble = node.querySelector(".bubble");
  if (bubble) bubble.innerHTML = messageTextMarkup(message.text, message.typing);
  renderLiveTimeline(node, message.live);
  node.className = `message ${message.role}${message.typing ? " typing" : ""}`;
  if (shouldStick) scrollFeed();
}

function renderLiveTimeline(node, items = []) {
  const existingLive = node.querySelector(".live-timeline");
  const live = (items || []).slice(-10);
  if (!live.length) {
    if (existingLive) existingLive.remove();
    return;
  }
  if (!existingLive) {
    node.insertAdjacentHTML("beforeend", liveTimelineMarkup(live));
    return;
  }
  const seen = new Set();
  live.forEach((item, index) => {
    const key = String(item.key || `${item.kind || "live"}:${index}`);
    seen.add(key);
    let line = Array.from(existingLive.querySelectorAll(".live-line"))
      .find((candidate) => candidate.dataset.liveKey === key);
    if (!line) {
      existingLive.insertAdjacentHTML("beforeend", liveLineMarkup(item, index));
      line = existingLive.lastElementChild;
      if (line) line.dataset.liveKey = key;
    }
    if (!line) return;
    line.className = `live-line ${item.status || ""}`;
    line.querySelector("span").textContent = item.kind || "live";
    line.querySelector("b").textContent = item.title || "";
    line.querySelector("em").textContent = item.body || "";
  });
  existingLive.querySelectorAll(".live-line").forEach((line) => {
    if (!seen.has(line.dataset.liveKey || "")) line.remove();
  });
}

function appendLiveEvent(id, item) {
  touchLiveTurn(id, {
    status: item.status === "failed" ? "failed" : item.status === "done" ? "done" : "running",
    lastKind: item.kind || "live",
    lastTitle: item.title || "",
  });
  const targetSessionId = state.taskSessions[id];
  const entry = {
    kind: item.kind || "live",
    title: oneLine(item.title || "", 64),
    body: oneLine(item.body || "", 180),
    status: item.status || "",
    key: item.key || "",
    at: Date.now(),
  };
  if (targetSessionId && targetSessionId !== state.currentSessionId) {
    const session = state.sessions.find((candidate) => candidate.id === targetSessionId);
    if (session) {
      const messages = session.messages || [];
      let message = messages.find((candidate) => candidate.id === id && candidate.role === "assistant");
      if (!message) {
        message = { id, role: "assistant", label: "Crypt", text: "", uiId: `stored-${id}`, live: [] };
        messages.push(message);
      }
      message.live = mergeLiveItems(message.live, entry);
      session.messages = messages.slice(-MAX_SESSION_MESSAGES);
      session.updatedAt = Date.now();
      saveChatSessions();
    }
    return;
  }
  let message = state.messages.find((candidate) => candidate.id === id && candidate.role === "assistant");
  if (!message) {
    message = { id, role: "assistant", label: "Crypt", text: "", typing: true, live: [] };
    ensureMessageId(message);
    state.messages.push(message);
  }
  message.live = mergeLiveItems(message.live, entry);
  persistCurrentSession(false);
  if (state.currentView === "chat") updateMessageNode(message);
}

function mergeLiveItems(items = [], entry) {
  const current = [...(items || [])];
  if (entry.key) {
    const index = current.findIndex((item) => item.key === entry.key);
    if (index >= 0) {
      current[index] = { ...current[index], ...entry };
      return current.slice(-10);
    }
  }
  const last = current[current.length - 1];
  if (
    last &&
    last.kind === entry.kind &&
    last.title === entry.title &&
    last.body === entry.body &&
    last.status === entry.status
  ) {
    current[current.length - 1] = { ...last, at: entry.at };
    return current.slice(-10);
  }
  return [...current, entry].slice(-10);
}

function finishLiveEvents(id) {
  touchLiveTurn(id, { status: "done" });
  const targetSessionId = state.taskSessions[id];
  if (targetSessionId && targetSessionId !== state.currentSessionId) {
    const session = state.sessions.find((candidate) => candidate.id === targetSessionId);
    const message = (session?.messages || []).find((candidate) => candidate.id === id && candidate.role === "assistant");
    if (!message?.live?.length) return;
    message.live = message.live.map((item) => (
      item.status === "running" ? { ...item, status: "done" } : item
    ));
    session.updatedAt = Date.now();
    saveChatSessions();
    return;
  }
  const message = state.messages.find((candidate) => candidate.id === id && candidate.role === "assistant");
  if (!message?.live?.length) return;
  message.live = message.live.map((item) => (
    item.status === "running" ? { ...item, status: "done" } : item
  ));
  persistCurrentSession(false);
  if (state.currentView === "chat") updateMessageNode(message);
}

function currentAssistantText(id) {
  const targetSessionId = state.taskSessions[id];
  if (targetSessionId && targetSessionId !== state.currentSessionId) {
    const session = state.sessions.find((candidate) => candidate.id === targetSessionId);
    const message = (session?.messages || []).find((candidate) => candidate.id === id && candidate.role === "assistant");
    return message?.text || "";
  }
  return state.messages.find((candidate) => candidate.id === id && candidate.role === "assistant")?.text || "";
}

function startLivePulse(id) {
  touchLiveTurn(id, { status: "running" });
  if (state.liveTimers[id]) return;
  const started = Date.now();
  const lines = [
    "Thinking through the request.",
    "Checking the route and context.",
    "Waiting on the model stream.",
    "Watching for tool calls.",
  ];
  let tick = 0;
  const update = () => {
    const elapsed = Math.max(1, Math.round((Date.now() - started) / 1000));
    appendLiveEvent(id, {
      key: "thinking-pulse",
      kind: "thinking",
      title: "Thinking",
      body: `${lines[tick % lines.length]} ${elapsed}s`,
      status: "running",
    });
    tick += 1;
  };
  update();
  state.liveTimers[id] = window.setInterval(update, 1200);
}

function stopLivePulse(id) {
  const timer = state.liveTimers[id];
  if (timer) window.clearInterval(timer);
  delete state.liveTimers[id];
}

function touchLiveTurn(id, patch = {}) {
  if (!id) return null;
  const now = Date.now();
  const existing = state.liveTurns[id] || { id, startedAt: now, updatedAt: now, status: "running" };
  state.liveTurns[id] = {
    ...existing,
    ...patch,
    id,
    updatedAt: now,
  };
  return state.liveTurns[id];
}

function registerEventSession(event, id) {
  if (!id || !event.sessionKey) return;
  state.taskSessions[id] = String(event.sessionKey);
  touchLiveTurn(id, { sessionKey: String(event.sessionKey) });
}

function addActivity(title, body = "", kind = "event") {
  const item = document.createElement("article");
  item.className = `activity-item activity-${String(kind || "event").replace(/[^a-z0-9_-]/gi, "")}`;
  item.innerHTML = `
    <i aria-hidden="true"></i>
    <strong>${escapeHtml(oneLine(title, 80))}</strong>
    <span>${escapeHtml(oneLine(body, 220))}</span>
  `;
  const feed = $("#activityFeed");
  feed.prepend(item);
  while (feed.children.length > 80) feed.lastElementChild?.remove();
}

function friendlyToolName(name) {
  const value = String(name || "tool");
  const map = {
    read_file: "Reading files",
    write_file: "Writing files",
    edit_file: "Editing files",
    shell: "Running command",
    web_search: "Searching web",
    fetch_url: "Opening page",
    spawn_agent: "Delegating work",
  };
  return map[value] || value.replaceAll("_", " ");
}

function handleEvent(event) {
  if (event.seq) state.seq = Math.max(state.seq, Number(event.seq));
  state.events.push(event);
  if (state.events.length > 300) state.events = state.events.slice(-300);
  const id = event.id || "default";
  registerEventSession(event, id);
  switch (event.event) {
    case "snapshot":
      if (event.snapshot) {
        state.snapshot = event.snapshot;
        renderShell();
      }
      break;
    case "taskStarted":
      state.busy = true;
      setStatus("Working");
      updateAssistantMessage(id, "", { typing: true });
      startLivePulse(id);
      addActivity("Started", event.prompt || "New request", "mission");
      break;
    case "taskProgress":
      appendLiveEvent(id, {
        key: `progress:${event.phase || "work"}`,
        kind: event.phase || "progress",
        title: event.phase === "provider" ? "Engine" : "Working",
        body: event.text || "",
        status: "running",
      });
      addActivity(event.phase || "Progress", event.text || "");
      break;
    case "intentRouted":
      appendLiveEvent(id, {
        key: "intent-route",
        kind: "route",
        title: `Intent: ${event.intent || "task"}`,
        body: event.rationale || event.text || "",
        status: "running",
      });
      addActivity("Intent", `${event.intent || "task"} / ${(Number(event.confidence || 0) * 100).toFixed(0)}%`, "mission");
      break;
    case "thinkingDelta":
      appendLiveEvent(id, {
        key: "thinking-stream",
        kind: "thinking",
        title: "Thinking",
        body: event.text ? oneLine(event.text, 180) : "Reasoning stream active.",
        status: "running",
      });
      break;
    case "assistantDelta":
      updateAssistantMessage(id, event.text || "", { append: true, typing: true });
      break;
    case "taskFinished":
      state.busy = false;
      setStatus("Ready");
      stopLivePulse(id);
      finishLiveEvents(id);
      updateAssistantMessage(id, event.text || currentAssistantText(id) || "Done.", { typing: false });
      maybeSpeak(event.text || "").catch((error) => addActivity("Voice", error.message));
      delete state.taskSessions[id];
      if (event.snapshot) state.snapshot = event.snapshot;
      renderShell();
      if (state.currentView !== "chat") renderCurrentView();
      addActivity("Finished", "Request complete");
      break;
    case "taskFailed":
      state.busy = false;
      setStatus("Needs attention");
      stopLivePulse(id);
      touchLiveTurn(id, { status: "failed" });
      appendLiveEvent(id, { kind: "error", title: "Stopped", body: event.error || "", status: "failed" });
      updateAssistantMessage(id, event.error || "Something failed.", { typing: false });
      delete state.taskSessions[id];
      addActivity("Stopped", event.error || "");
      break;
    case "toolProgress":
      appendLiveEvent(id, {
        key: `tool:${event.callId || event.tool || "progress"}`,
        kind: "tool",
        title: friendlyToolName(event.tool),
        body: event.text || "Receiving tool input.",
        status: "running",
      });
      addActivity(friendlyToolName(event.tool), event.text || "", "tool");
      break;
    case "toolCall":
    case "toolStarted":
      appendLiveEvent(id, {
        key: `tool:${event.callId || event.tool || "started"}`,
        kind: "tool",
        title: friendlyToolName(event.tool),
        body: event.text || event.callId || "Tool started.",
        status: "running",
      });
      addActivity(friendlyToolName(event.tool), event.text || "", "tool");
      break;
    case "toolResult":
      appendLiveEvent(id, {
        key: `tool:${event.callId || event.tool || "result"}`,
        kind: "tool",
        title: event.ok === false ? "Tool failed" : "Tool finished",
        body: toolResultSummary(event),
        status: event.ok === false ? "failed" : "done",
      });
      addActivity(event.ok === false ? "Tool failed" : "Tool finished", toolResultSummary(event), event.ok === false ? "error" : "tool");
      break;
    case "approvalRequested":
      showApproval(event);
      appendLiveEvent(id, {
        kind: "approval",
        title: "Permission needed",
        body: event.text || event.question || "",
        status: "running",
      });
      addActivity("Waiting for permission", event.text || event.question || "", "approval");
      break;
    case "approvalResolved":
      hideApproval();
      appendLiveEvent(id, {
        kind: "approval",
        title: event.approved ? "Approved" : "Denied",
        body: event.text || "",
        status: event.approved ? "done" : "failed",
      });
      addActivity(event.approved ? "Approved" : "Denied", event.text || "", "approval");
      break;
    case "commandResult":
      updateAssistantMessage(id, textFrom(event), { typing: false });
      addActivity("Command", event.command || "");
      break;
    case "autonomyQuiet":
      addActivity("Autonomy", event.text === "no autonomous changes needed" ? "Nothing new to update." : textFrom(event));
      break;
    case "memoryLearned":
      addActivity("Memory updated", oneLine(event.text || "Saved a useful signal.", 160));
      break;
    case "memoryJournalUpdated":
      addActivity(
        event.promoted ? "Long-term memory" : "Working memory",
        oneLine(event.text || "Updated the memory journal.", 160),
      );
      refresh({ renderView: state.currentView === "memory" || state.currentView === "persona" }).catch((error) => addActivity("Memory", error.message));
      break;
    case "memoryJournalError":
      addActivity("Memory journal", event.error || "Could not update journal.");
      break;
    case "entitiesUpdated":
      addActivity("Entity memory", oneLine(event.text || "Typed entity memory updated.", 160));
      refresh({ renderView: state.currentView === "memory" || state.currentView === "persona" }).catch((error) => addActivity("Entities", error.message));
      break;
    case "entitiesError":
      addActivity("Entity memory", event.error || "Could not update entity memory.");
      break;
    case "businessEntitiesUpdated":
      addActivity("Business registry", oneLine(event.text || "Business entities updated.", 160), "mission");
      refresh({ renderView: state.currentView === "memory" || state.currentView === "missions" }).catch((error) => addActivity("Business registry", error.message));
      break;
    case "businessEntitiesError":
      addActivity("Business registry", event.error || "Could not update business registry.");
      break;
    case "externalDraftCreated":
      appendLiveEvent(id, {
        key: `external-draft:${event.draft?.draft_id || "queued"}`,
        kind: "approval",
        title: "External draft queued",
        body: event.text || "Approval required before anything external happens.",
        status: "running",
      });
      addActivity("External draft", oneLine(event.text || "Approval-gated draft queued.", 160), "approval");
      refresh({ renderView: state.currentView === "jobs" }).catch((error) => addActivity("Drafts", error.message));
      break;
    case "externalDraftError":
      addActivity("External draft", event.error || "Could not queue approval draft.");
      break;
    case "outcomeLearned":
      addActivity("Outcome learned", oneLine(event.text || "Saved an outcome lesson.", 180), "mission");
      refresh({ renderView: state.currentView === "memory" || state.currentView === "jobs" }).catch((error) => addActivity("Learning", error.message));
      break;
    case "outcomeLearnError":
      addActivity("Outcome learning", event.error || "Could not record outcome lesson.");
      break;
    case "agentDelegation":
      addActivity(
        "Agent routing",
        `${event.action || "local"}${event.agentName ? ` / ${event.agentName}` : ""}: ${oneLine(event.text || "", 120)}`,
        "mission",
      );
      refresh({ renderView: state.currentView === "agents" }).catch((error) => addActivity("Agents", error.message));
      break;
    case "agentDelegationError":
      addActivity("Agent routing", event.error || "Could not update delegation state.");
      break;
    case "missionCreated":
      addActivity("Mission created", oneLine(event.text || event.goal?.title || "Autonomous mission saved.", 160), "mission");
      refresh({ renderView: state.currentView === "missions" }).catch((error) => addActivity("Missions", error.message));
      break;
    case "missionMatched":
      addActivity("Mission matched", oneLine(event.text || event.goal?.title || "Using the existing autonomous mission.", 160), "mission");
      refresh({ renderView: state.currentView === "missions" }).catch((error) => addActivity("Missions", error.message));
      break;
    case "workThreadUpdated":
      addActivity("Work thread", oneLine(event.nextAction || event.text || "Thread updated.", 160), "mission");
      refresh({ renderView: state.currentView === "missions" || state.currentView === "jobs" }).catch((error) => addActivity("Threads", error.message));
      break;
    case "browserActivity":
      addActivity("Browser", event.url ? `${event.text} / ${event.url}` : event.text, "browser");
      break;
    case "desktopActivity":
      addActivity("Desktop", event.action ? `${event.action}: ${event.text}` : event.text, "desktop");
      break;
    case "missionStep":
      addActivity("Mission step", event.text || "", "mission");
      break;
    case "workThreadError":
      addActivity("Work thread", event.error || "Could not update thread.");
      break;
    case "missionError":
      addActivity("Mission router", event.error || "Could not inspect mission need.");
      break;
    case "error":
      state.busy = false;
      setStatus("Needs attention");
      touchLiveTurn(id, { status: "failed" });
      pushMessage({ role: "system", label: "Crypt", text: event.error || "Something failed." });
      addActivity("Error", event.error || "");
      break;
    default:
      if (event.text || event.error) addActivity(event.event || "Event", textFrom(event));
  }
  if (state.currentView === "jobs") renderCurrentView();
}

async function refresh({ renderView = false } = {}) {
  const snapshot = await json("/api/snapshot");
  const firstSnapshot = !state.snapshot;
  state.snapshot = snapshot;
  renderShell(snapshot);
  if (firstSnapshot || renderView) renderCurrentView();
}

async function pollEvents() {
  if (state.poll.eventsStarted) return;
  state.poll.eventsStarted = true;
  await pollEventsOnce();
}

async function pollEventsOnce() {
  try {
    const data = await json(`/api/events?since=${state.seq}`);
    (data.events || []).forEach(handleEvent);
  } catch (error) {
    addActivity("WebUI", error.message);
  } finally {
    setTimeout(pollEventsOnce, state.busy ? 280 : 900);
  }
}

async function pollSnapshot() {
  if (state.poll.snapshotStarted) return;
  state.poll.snapshotStarted = true;
  await pollSnapshotOnce();
}

async function pollSnapshotOnce() {
  try {
    if (!state.busy) {
      await refresh({ renderView: false });
    }
  } catch (error) {
    addActivity("WebUI", error.message);
  } finally {
    setTimeout(pollSnapshotOnce, state.busy ? 2400 : 5000);
  }
}

async function setEngine(provider, model) {
  if (!provider || !model) return;
  state.engine.provider = provider;
  state.engine.model = model;
  setText("#enginePill", `${providerLabel(provider, state.snapshot)} / ${modelLabel(model, state.snapshot)}`);
  try {
    await json("/api/engine", {
      method: "POST",
      body: JSON.stringify({ provider, model }),
    });
  } catch (error) {
    addActivity("Engine", error.message);
  }
}

function syncComposerAdvanced() {
  const panel = $("#composerAdvanced");
  const button = $("#composerAdvancedButton");
  if (!panel || !button) return;
  panel.hidden = !state.composer.advanced;
  button.classList.toggle("active", state.composer.advanced);
  button.setAttribute("aria-expanded", String(state.composer.advanced));
  button.textContent = state.composer.advanced ? "Hide" : "Options";
}

function toggleComposerAdvanced() {
  state.composer.advanced = !state.composer.advanced;
  localStorage.setItem("crypt.composer.advanced", state.composer.advanced ? "1" : "0");
  syncComposerAdvanced();
  $("#prompt").focus();
}

function handleProviderChange() {
  const provider = $("#providerSelect")?.value || "";
  const models = modelsFor(provider, state.snapshot);
  const model = models[0] || "";
  const modelSelect = $("#modelSelect");
  if (modelSelect) modelSelect.innerHTML = modelOptionMarkup(models, model);
  setEngine(provider, model);
}

function handleModelChange() {
  setEngine($("#providerSelect")?.value || "", $("#modelSelect")?.value || "");
}

function selectedRoute() {
  const value = $("#routeSelect")?.value || "auto";
  return {
    auto: "",
    think: "planner",
    build: "builder",
    review: "reviewer",
    fast: "fast",
  }[value] || "";
}

async function sendPrompt(text) {
  if (!String(text || "").trim()) {
    flushVoiceInterim();
    text = $("#prompt").value;
  }
  const trimmed = text.trim();
  if (!trimmed || state.busy) return;
  const requestId = `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const sessionId = currentSession().id;
  if (state.voice.desired || state.voice.listening) stopVoice();
  stopVoicePlayback();
  $("#prompt").value = "";
  resizePrompt();
  pushMessage({ role: "user", label: "You", text: trimmed });
  state.taskSessions[requestId] = sessionId;
  state.busy = true;
  setStatus("Working");
  setView("chat");
  updateAssistantMessage(requestId, "", { typing: true });
  startLivePulse(requestId);
  try {
    await json("/api/prompt", {
      method: "POST",
      body: JSON.stringify({
        id: requestId,
        text: trimmed,
        route: selectedRoute(),
        agentId: state.engine.agentId || "",
        sessionKey: sessionId,
      }),
    });
  } catch (error) {
    stopLivePulse(requestId);
    delete state.taskSessions[requestId];
    state.busy = false;
    setStatus("Needs attention");
    pushMessage({ role: "system", label: "Crypt", text: error.message });
  }
}

async function submitGoal(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await json("/api/goals", {
    method: "POST",
    body: JSON.stringify({
      title: form.get("title"),
      successMetric: form.get("successMetric"),
      cadence: form.get("cadence"),
      priority: 4,
    }),
  });
  event.currentTarget.reset();
  await refresh({ renderView: true });
}

async function submitLesson(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await json("/api/lessons", {
    method: "POST",
    body: JSON.stringify({ text: form.get("text"), tags: ["webui", "memory"] }),
  });
  event.currentTarget.reset();
  await refresh({ renderView: true });
}

async function submitPreference(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await json("/api/lessons", {
    method: "POST",
    body: JSON.stringify({ text: form.get("text"), tags: ["voice", "preference", "persona"] }),
  });
  event.currentTarget.reset();
  await json("/api/autonomy", { method: "POST", body: JSON.stringify({ limit: 3 }) });
  await refresh({ renderView: true });
}

async function submitForge(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  await json("/api/forge", {
    method: "POST",
    body: JSON.stringify({ topic: form.get("topic"), minLessons: 1 }),
  });
  event.currentTarget.reset();
  await refresh({ renderView: true });
}

async function submitAgent(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const name = String(form.get("name") || "").trim();
  const purpose = String(form.get("purpose") || "").trim();
  if (!name && !purpose) return;
  await json("/api/agents", {
    method: "POST",
    body: JSON.stringify({
      name,
      purpose,
      agentType: form.get("agentType"),
      provider: form.get("provider"),
      model: form.get("model"),
    }),
  });
  event.currentTarget.reset();
  state.shellKeys.agents = "";
  await refresh({ renderView: true });
}

async function runAutonomy() {
  await json("/api/autonomy", { method: "POST", body: JSON.stringify({ limit: 5 }) });
  await refresh({ renderView: true });
}

function resizePrompt() {
  const prompt = $("#prompt");
  prompt.style.height = "auto";
  prompt.style.height = `${Math.min(prompt.scrollHeight, 190)}px`;
}

function showApproval(event) {
  state.activeApproval = event.approvalId;
  $("#approvalText").textContent = event.question || event.text || "Crypt needs permission to continue.";
  $("#approvalTray").hidden = false;
}

function hideApproval() {
  state.activeApproval = null;
  $("#approvalTray").hidden = true;
}

async function answerApproval(approved) {
  if (!state.activeApproval) return;
  const approvalId = state.activeApproval;
  hideApproval();
  await json("/api/approval", {
    method: "POST",
    body: JSON.stringify({ approvalId, approved }),
  });
}

function toggleActivity(force) {
  state.activityOpen = typeof force === "boolean" ? force : !state.activityOpen;
  $("#activityPanel").classList.toggle("open", state.activityOpen);
  $("#activityPanel").setAttribute("aria-hidden", String(!state.activityOpen));
  $("#activityButton").setAttribute("aria-expanded", String(state.activityOpen));
}

function scrollFeed() {
  const feed = $("#feed");
  if (feed) feed.scrollTop = feed.scrollHeight;
}

function isFeedNearBottom(feed = $("#feed")) {
  if (!feed) return true;
  return feed.scrollHeight - feed.scrollTop - feed.clientHeight < STICKY_SCROLL_PX;
}

function updateVoiceUi(text) {
  const button = $("#voiceButton");
  const status = $("#voiceStatus");
  if (button) {
    button.classList.toggle("active", state.voice.listening || state.voice.desired);
    button.setAttribute("aria-pressed", String(state.voice.listening || state.voice.desired));
    button.querySelector("span").textContent = state.voice.listening ? "live" : "mic";
  }
  if (status) status.textContent = text;
}

function clearVoiceRestart() {
  if (!state.voice.restartTimer) return;
  window.clearTimeout(state.voice.restartTimer);
  state.voice.restartTimer = 0;
}

function scheduleVoiceRestart() {
  if (!state.voice.desired || state.voice.manuallyStopping) return;
  clearVoiceRestart();
  state.voice.restartAttempts += 1;
  const delay = Math.min(900, 140 + state.voice.restartAttempts * 120);
  updateVoiceUi("reconnecting mic");
  state.voice.restartTimer = window.setTimeout(() => {
    state.voice.restartTimer = 0;
    startVoice();
  }, delay);
}

function ensureVoice() {
  if (state.voice.supported === false) return null;
  if (state.voice.recognition) return state.voice.recognition;
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    state.voice.supported = false;
    updateVoiceUi("voice unsupported");
    return null;
  }
  const recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "en-US";
  recognition.onstart = () => {
    state.voice.listening = true;
    state.voice.manuallyStopping = false;
    state.voice.restartAttempts = 0;
    clearVoiceRestart();
    updateVoiceUi("listening");
  };
  recognition.onresult = (event) => {
    let finalText = "";
    let interimText = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      const text = result[0]?.transcript || "";
      if (result.isFinal) finalText += text;
      else interimText += text;
    }
    if (finalText.trim()) {
      appendTranscript(finalText);
      state.voice.interim = "";
    } else {
      state.voice.interim = interimText.trim();
    }
    updateVoiceUi(interimText.trim() ? `hearing: ${oneLine(interimText, 32)}` : "listening");
  };
  recognition.onerror = (event) => {
    const error = event.error || "voice error";
    if (error === "not-allowed" || error === "service-not-allowed") {
      state.voice.desired = false;
      state.voice.listening = false;
      state.voice.interim = "";
      updateVoiceUi("mic blocked");
      return;
    }
    updateVoiceUi(error === "no-speech" ? "listening" : error);
  };
  recognition.onend = () => {
    state.voice.listening = false;
    if (state.voice.desired && !state.voice.manuallyStopping) {
      scheduleVoiceRestart();
      return;
    }
    state.voice.desired = false;
    state.voice.manuallyStopping = false;
    state.voice.restartAttempts = 0;
    updateVoiceUi("voice ready");
  };
  state.voice.recognition = recognition;
  state.voice.supported = true;
  return recognition;
}

function appendTranscript(text) {
  const prompt = $("#prompt");
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!prompt || !clean) return;
  const prefix = prompt.value.trim() ? " " : "";
  prompt.value = `${prompt.value}${prefix}${clean}`;
  resizePrompt();
  prompt.focus();
}

function flushVoiceInterim() {
  const clean = String(state.voice.interim || "").replace(/\s+/g, " ").trim();
  if (!clean) return;
  appendTranscript(clean);
  state.voice.interim = "";
  updateVoiceUi(state.voice.listening ? "listening" : "voice ready");
}

function startVoice() {
  const recognition = ensureVoice();
  if (!recognition) return;
  if (state.voice.listening) {
    updateVoiceUi("listening");
    return;
  }
  state.voice.desired = true;
  state.voice.manuallyStopping = false;
  clearVoiceRestart();
  try {
    recognition.start();
  } catch (error) {
    if (state.voice.desired && !state.voice.listening) scheduleVoiceRestart();
    else updateVoiceUi(state.voice.listening ? "listening" : "mic starting");
  }
}

function stopVoice() {
  const recognition = ensureVoice();
  clearVoiceRestart();
  state.voice.desired = false;
  state.voice.listening = false;
  state.voice.manuallyStopping = true;
  state.voice.interim = "";
  updateVoiceUi("voice ready");
  try {
    recognition?.stop();
  } catch (error) {
    state.voice.listening = false;
  }
}

function toggleVoice() {
  if (state.voice.desired || state.voice.listening) stopVoice();
  else startVoice();
}

function toggleVoiceOutput() {
  const ready = Boolean(state.snapshot?.voice?.ready);
  if (!ready) {
    setTtsStatus("run setup first");
    return;
  }
  state.voiceOut.enabled = !state.voiceOut.enabled;
  localStorage.setItem("crypt.voice.output.enabled", state.voiceOut.enabled ? "1" : "0");
  syncVoiceOutputControls(state.snapshot);
  if (state.voiceOut.enabled) testVoiceOutput();
}

function handleTtsVoiceChange(event) {
  state.voiceOut.voice = event.currentTarget.value || "af_heart";
  localStorage.setItem("crypt.voice.output.voice", state.voiceOut.voice);
  syncVoiceOutputControls(state.snapshot);
}

async function testVoiceOutput() {
  await speakText("Crypt voice is online. Local Kokoro is ready.", { force: true });
}

async function maybeSpeak(text) {
  if (!state.voiceOut.enabled) return;
  if (!shouldSpeakResponse(text)) {
    setTtsStatus("speech skipped");
    return;
  }
  if (state.voice.desired || state.voice.listening) stopVoice();
  await speakText(text, { force: false });
}

function shouldSpeakResponse(text) {
  const clean = voiceTextForSpeech(text);
  if (!clean) return false;
  if (/\[tool_(?:result|call):/i.test(clean)) return false;
  if (/schema validation failed|traceback|permissionerror|<html|<\/[a-z]+>/i.test(clean)) return false;
  return true;
}

function voiceTextForSpeech(text) {
  return String(text || "")
    .replace(/```[\s\S]*?```/g, " code omitted ")
    .replace(/`([^`\n]+?)`/g, "$1")
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/[*_~>#-]+/g, " ")
    .replace(/[\p{Extended_Pictographic}\uFE0F\u200D]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function speakText(text, { force = false } = {}) {
  const clean = voiceTextForSpeech(text);
  if (!clean) return;
  if (!force && !state.snapshot?.voice?.ready) return;
  const token = Date.now() + Math.random();
  state.voiceOut.speakToken = token;
  stopVoicePlayback();
  state.voiceOut.busy = true;
  setTtsStatus("kokoro speaking");
  syncVoiceOutputControls(state.snapshot);
  try {
    const data = await json("/api/voice/speak", {
      method: "POST",
      body: JSON.stringify({
        text: clean,
        voice: state.voiceOut.voice,
        speed: state.voiceOut.speed,
      }),
    });
    const audioUrl = data.speech?.audio_url || data.speech?.audioUrl;
    if (!audioUrl) throw new Error("voice audio missing");
    if (state.voiceOut.speakToken !== token) return;
    await playVoiceAudio(audioUrl);
    setTtsStatus("kokoro ready");
  } catch (error) {
    setTtsStatus(error.message.includes("Kokoro voice is not ready") ? "kokoro setup needed" : oneLine(error.message, 42));
    addActivity("Voice", error.message);
  } finally {
    if (state.voiceOut.speakToken === token) {
      state.voiceOut.busy = false;
      syncVoiceOutputControls(state.snapshot);
    }
  }
}

async function playVoiceAudio(audioUrl) {
  stopVoicePlayback();
  const audio = new Audio(`${audioUrl}${audioUrl.includes("?") ? "&" : "?"}t=${Date.now()}`);
  state.voiceOut.audio = audio;
  await audio.play();
}

function stopVoicePlayback() {
  if (!state.voiceOut.audio) return;
  state.voiceOut.audio.pause();
  state.voiceOut.audio = null;
}

function setTtsStatus(text) {
  const node = $("#ttsStatus");
  if (node) node.textContent = text;
}

function startAmbient() {
  if (state.animationStarted) return;
  state.animationStarted = true;
  const canvas = $("#ambient");
  const ctx = canvas.getContext("2d");
  const points = Array.from({ length: 72 }, (_, index) => ({
    x: Math.random(),
    y: Math.random(),
    r: 1 + (index % 3) * .35,
    speed: .0002 + (index % 6) * .00008,
  }));

  function size() {
    const scale = window.devicePixelRatio || 1;
    canvas.width = Math.floor(window.innerWidth * scale);
    canvas.height = Math.floor(window.innerHeight * scale);
    canvas.style.width = `${window.innerWidth}px`;
    canvas.style.height = `${window.innerHeight}px`;
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
  }

  function frame(time) {
    const width = window.innerWidth;
    const height = window.innerHeight;
    ctx.clearRect(0, 0, width, height);
    ctx.globalAlpha = .16;
    ctx.strokeStyle = "#2a6e61";
    ctx.lineWidth = 1;
    for (let x = -120 + ((time * .014) % 120); x < width + 120; x += 120) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x + height * .20, height);
      ctx.stroke();
    }
    ctx.globalAlpha = .8;
    for (const point of points) {
      point.y = (point.y + point.speed) % 1;
      ctx.beginPath();
      ctx.fillStyle = point.r > 1.5 ? "#f4a33a" : "#65e0cb";
      ctx.arc(point.x * width, point.y * height, point.r, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(frame);
  }

  size();
  window.addEventListener("resize", size);
  requestAnimationFrame(frame);
}

$("#promptForm").addEventListener("submit", (event) => {
  event.preventDefault();
  flushVoiceInterim();
  sendPrompt($("#prompt").value);
});

$("#prompt").addEventListener("input", resizePrompt);
$("#prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    flushVoiceInterim();
    sendPrompt($("#prompt").value);
  }
});

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view || "panel"));
});

$("#providerSelect").addEventListener("change", handleProviderChange);
$("#modelSelect").addEventListener("change", handleModelChange);
$("#composerAdvancedButton").addEventListener("click", toggleComposerAdvanced);
$("#routeSelect").addEventListener("change", (event) => {
  state.engine.route = event.currentTarget.value || "auto";
  $("#prompt").focus();
});
$("#agentSelect").addEventListener("change", (event) => {
  state.engine.agentId = event.currentTarget.value || "";
  $("#prompt").focus();
});
$("#voiceButton").addEventListener("click", toggleVoice);
$("#ttsToggle").addEventListener("click", toggleVoiceOutput);
$("#ttsVoiceSelect").addEventListener("change", handleTtsVoiceChange);
$("#ttsTestButton").addEventListener("click", testVoiceOutput);
$("#sessionList").addEventListener("click", (event) => {
  const button = event.target.closest("[data-session-id]");
  if (button) switchChatSession(button.dataset.sessionId || "");
});

$("#searchButton").addEventListener("click", () => {
  setView("chat");
  $("#prompt").value = "Search for ";
  $("#prompt").focus();
  resizePrompt();
});
$("#newChatButton").addEventListener("click", () => {
  createChatSession();
  setView("chat");
});
$("#activityButton").addEventListener("click", () => toggleActivity());
$("#coreButton").addEventListener("click", () => toggleActivity());
$("#closeActivityButton").addEventListener("click", () => toggleActivity(false));
$("#approveButton").addEventListener("click", () => answerApproval(true));
$("#denyButton").addEventListener("click", () => answerApproval(false));

loadChatSessions();
syncComposerAdvanced();
startAmbient();
refresh().then(() => {
  pollEvents();
  pollSnapshot();
});
