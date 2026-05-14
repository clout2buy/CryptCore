const state = {
  seq: 0,
  busy: false,
  activeApproval: null,
  activityOpen: false,
  currentView: "panel",
  intents: new Set(),
  snapshot: null,
  events: [],
  messages: [],
  messageSeq: 0,
  animationStarted: false,
};

const viewMeta = {
  panel: ["Home", "Crypt Console"],
  chat: ["Chat", "Conversation"],
  files: ["Files", "Workspace Files"],
  terminal: ["Terminal", "Command Surface"],
  jobs: ["Jobs", "Runtime Work"],
  missions: ["Missions", "Goals And Schedules"],
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

function renderShell(snapshot = state.snapshot) {
  if (!snapshot) return;
  $("#enginePill").textContent = `${snapshot.provider || "crypt"} / ${snapshot.model || "auto"}`;
  $("#sessionCount").textContent = String((snapshot.sessionsPreview || []).length);
  $("#sessionList").innerHTML = (snapshot.sessionsPreview || [])
    .slice(0, 6)
    .map((session) => `
      <article class="mini-item">
        <b>${escapeHtml(session.title || "New conversation")}</b>
        <span>${escapeHtml(session.message_count || 0)} msgs / ${escapeHtml(session.model || "auto")}</span>
      </article>
    `)
    .join("") || `<article class="mini-item empty"><b>No sessions yet</b><span>Start a conversation.</span></article>`;
  renderCoreFeatures(snapshot.coreFeatures || []);
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
  const active = [
    ["Engine", `${snapshot.provider || "crypt"} / ${snapshot.model || "auto"}`],
    ["Tools", snapshot.tools || 0],
    ["Memory", snapshot.lessons || 0],
    ["Autonomy", snapshot.autonomyCycles || 0],
  ];
  return `
    <section class="command-center">
      <div class="hero-card">
        <p>Crypt is listening</p>
        <h3>What should Crypt handle?</h3>
        <div class="hero-copy">Talk normally. Crypt can inspect files, use tools, remember what matters, and turn vague goals into concrete work.</div>
        <div class="hero-meta">
          <span>Autonomous runtime</span>
          <span>Memory online</span>
          <span>Tool access ready</span>
        </div>
        <div class="signal-strip" aria-hidden="true"><span></span></div>
      </div>
      <div class="stat-grid">
        ${active.map(([label, value]) => statCard(label, value)).join("")}
      </div>
    </section>
    <section class="feature-grid">
      ${features.slice(0, 12).map((feature) => featureCard(feature)).join("")}
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
            <h3>What are we working on?</h3>
            <span>Say what you want done. Crypt routes the rest.</span>
          </article>
        `}
      </div>
    </section>
  `;
}

function filesView(snapshot) {
  const project = snapshot.project || {};
  const files = snapshot.filesPreview || [];
  return `
    <section class="two-col">
      <div class="panel-card wide">
        <h3>Workspace</h3>
        <p>${escapeHtml(snapshot.workspace || "")}</p>
        <div class="pill-row">
          ${(project.languages || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
          ${(project.frameworks || []).slice(0, 5).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
        </div>
      </div>
      <div class="panel-card">
        <h3>Ask Crypt</h3>
        <button class="ask-button" data-ask="Inspect this workspace and tell me what matters.">Inspect workspace</button>
        <button class="ask-button" data-ask="Find the next files we should edit for the current goal.">Find edit targets</button>
      </div>
    </section>
    <section class="data-list">
      ${files.map((file) => row(file.kind === "dir" ? "Folder" : "File", file.name, file.path)).join("") || emptyRow("No files listed")}
    </section>
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
    </section>
    <section class="data-list">${events.map((event) => row(event.event || "Event", textFrom(event), new Date((event.ts || 0) * 1000).toLocaleTimeString())).join("") || emptyRow("No runtime events yet")}</section>
  `;
}

function missionsView(snapshot) {
  const goals = snapshot.goals || [];
  return `
    <section class="two-col">
      <form id="goalForm" class="panel-card form-card">
        <h3>New Mission</h3>
        <input name="title" placeholder="Launch something, monitor revenue, build a tool...">
        <input name="successMetric" placeholder="What counts as success?">
        <input name="cadence" placeholder="Cadence: daily, weekly, Friday...">
        <button type="submit">Create mission</button>
      </form>
      <div class="panel-card">
        <h3>Autonomous Review</h3>
        <p>Goals with cadence get reviewed by the safe autonomy loop.</p>
        <button class="small-action" id="runAutonomyButton" type="button">Review now</button>
      </div>
    </section>
    <section class="data-list">${goals.map((goal) => row(goal.status || "Goal", goal.title, goal.success_metric || goal.cadence || goal.goal_id)).join("") || emptyRow("No missions yet")}</section>
  `;
}

function memoryView(snapshot) {
  const lessons = snapshot.lessonsPreview || [];
  return `
    <section class="two-col">
      <form id="lessonForm" class="panel-card form-card wide">
        <h3>Teach Crypt</h3>
        <textarea name="text" rows="3" placeholder="Something Crypt should remember permanently..."></textarea>
        <button type="submit">Remember</button>
      </form>
      <div class="panel-card">
        <h3>Memory</h3>
        ${statCard("Lessons", snapshot.lessons || 0)}
        ${statCard("Soul", snapshot.soul?.active ? "active" : "new")}
      </div>
    </section>
    <section class="data-list">${lessons.map((lesson) => row("Lesson", lesson.text, `${lesson.scope} / ${lesson.confidence}`)).join("") || emptyRow("No durable memory yet")}</section>
  `;
}

function skillsView(snapshot) {
  const skills = snapshot.skillsPreview || [];
  return `
    <section class="two-col">
      <form id="forgeForm" class="panel-card form-card">
        <h3>Create Skill</h3>
        <input name="topic" placeholder="Topic from repeated lessons">
        <button type="submit">Create</button>
      </form>
      <div class="panel-card">
        <h3>Skill Actions</h3>
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
      <form id="preferenceForm" class="panel-card form-card wide">
        <h3>Shape Crypt</h3>
        <textarea name="text" rows="3" placeholder="Example: Crypt should sound direct, calm, and less robotic."></textarea>
        <button type="submit">Save preference</button>
      </form>
      <div class="panel-card">
        <h3>Soul File</h3>
        <p>${escapeHtml(snapshot.soul?.path || "No soul file yet")}</p>
        ${statCard("Status", snapshot.soul?.active ? "active" : "new")}
      </div>
    </section>
  `;
}

function modelsView(snapshot) {
  return `<section class="feature-grid">${(snapshot.routes || []).map((route) => featureCard({ label: route.role, value: route.model, status: route.provider, detail: route.status })).join("")}</section>`;
}

function providersView(snapshot) {
  return `<section class="feature-grid">${(snapshot.providers || []).map((provider) => featureCard({ label: provider.label || provider.id, value: provider.status, status: provider.id, detail: provider.note || (provider.models || []).slice(0, 4).join(", ") })).join("")}</section>`;
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
  return `
    <section class="feature-grid">
      ${featureCard({ label: "Approval", value: snapshot.approval, status: snapshot.approvalMode, detail: "Controls when Crypt asks before tools run." })}
      ${featureCard({ label: "Thinking", value: snapshot.thinkingMode, status: snapshot.reasoningEffort, detail: "Provider reasoning mode." })}
      ${featureCard({ label: "Auth", value: snapshot.authOk ? "ready" : "missing", status: snapshot.auth, detail: snapshot.authMessage || "Provider is usable." })}
      ${featureCard({ label: "Workspace", value: "open", status: "local", detail: snapshot.workspace })}
    </section>
  `;
}

function statCard(label, value) {
  const text = String(value ?? "");
  const lengthClass = text.length > 14 ? " long" : "";
  return `<article class="stat-card${lengthClass}"><span>${escapeHtml(label)}</span><b>${escapeHtml(text)}</b></article>`;
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

function emptyRow(text) {
  return `<article class="data-row empty"><b>${escapeHtml(text)}</b><p>Ask Crypt to create it.</p></article>`;
}

function messageMarkup(message) {
  const uiId = ensureMessageId(message);
  return `
    <article class="message ${escapeHtml(message.role)}${message.typing ? " typing" : ""}" data-message-id="${uiId}">
      <span class="message-label">${escapeHtml(message.label || (message.role === "user" ? "You" : "Crypt"))}</span>
      <div class="bubble">${escapeHtml(message.text || (message.typing ? "Working on it." : ""))}</div>
    </article>
  `;
}

function attachViewHandlers() {
  document.querySelectorAll(".ask-button").forEach((button) => {
    button.addEventListener("click", () => sendPrompt(button.dataset.ask || button.textContent || ""));
  });
  const goalForm = $("#goalForm");
  if (goalForm) {
    goalForm.addEventListener("submit", submitGoal);
  }
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
  document.querySelectorAll("#runAutonomyButton").forEach((button) => {
    button.addEventListener("click", runAutonomy);
  });
}

function pushMessage(message) {
  ensureMessageId(message);
  state.messages.push(message);
  if (state.messages.length > 200) state.messages = state.messages.slice(-200);
  if (state.currentView === "chat") appendMessageNode(message);
}

function updateAssistantMessage(id, text, { append = false, typing = false } = {}) {
  let message = state.messages.find((item) => item.id === id && item.role === "assistant");
  if (!message) {
    message = { id, role: "assistant", label: "Crypt", text: "", typing };
    ensureMessageId(message);
    state.messages.push(message);
  }
  message.text = append ? message.text + text : text;
  message.typing = typing;
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
  const uiId = ensureMessageId(message);
  const node = feed.querySelector(`[data-message-id="${uiId}"]`);
  if (!node) {
    appendMessageNode(message);
    return;
  }
  const bubble = node.querySelector(".bubble");
  if (bubble) bubble.textContent = message.text || (message.typing ? "Working on it." : "");
  node.className = `message ${message.role}${message.typing ? " typing" : ""}`;
  scrollFeed();
}

function addActivity(title, body = "") {
  const item = document.createElement("article");
  item.className = "activity-item";
  item.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(body)}</span>`;
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
      addActivity("Started", event.prompt || "New request");
      break;
    case "assistantDelta":
      updateAssistantMessage(id, event.text || "", { append: true, typing: true });
      break;
    case "taskFinished":
      state.busy = false;
      setStatus("Ready");
      updateAssistantMessage(id, event.text || "Done.", { typing: false });
      if (event.snapshot) state.snapshot = event.snapshot;
      renderShell();
      if (state.currentView !== "chat") renderCurrentView();
      addActivity("Finished", "Request complete");
      break;
    case "taskFailed":
      state.busy = false;
      setStatus("Needs attention");
      updateAssistantMessage(id, event.error || "Something failed.", { typing: false });
      addActivity("Stopped", event.error || "");
      break;
    case "toolCall":
      addActivity(friendlyToolName(event.tool), event.text || "");
      break;
    case "toolResult":
      addActivity(event.ok === false ? "Tool failed" : "Tool finished", textFrom(event));
      break;
    case "approvalRequested":
      showApproval(event);
      addActivity("Waiting for permission", event.text || event.question || "");
      break;
    case "approvalResolved":
      hideApproval();
      addActivity(event.approved ? "Approved" : "Denied", event.text || "");
      break;
    case "commandResult":
      updateAssistantMessage(id, textFrom(event), { typing: false });
      addActivity("Command", event.command || "");
      break;
    case "autonomyQuiet":
      addActivity("Autonomy", event.text === "no autonomous changes needed" ? "Nothing new to update." : textFrom(event));
      break;
    case "error":
      state.busy = false;
      setStatus("Needs attention");
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

async function poll() {
  try {
    const data = await json(`/api/events?since=${state.seq}`);
    (data.events || []).forEach(handleEvent);
    await refresh({ renderView: false });
  } catch (error) {
    addActivity("WebUI", error.message);
  } finally {
    setTimeout(poll, 1200);
  }
}

async function sendPrompt(text) {
  const trimmed = text.trim();
  if (!trimmed || state.busy) return;
  $("#prompt").value = "";
  resizePrompt();
  pushMessage({ role: "user", label: "You", text: trimmed });
  state.busy = true;
  setStatus("Working");
  setView("chat");
  try {
    await json("/api/prompt", {
      method: "POST",
      body: JSON.stringify({ text: trimmed, intents: Array.from(state.intents) }),
    });
  } catch (error) {
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

function updateIntentPill() {
  const intents = Array.from(state.intents);
  $("#intentPill").textContent = intents.length ? intents.join(" + ") : "autopilot";
}

function toggleIntent(intent) {
  if (!intent) return;
  if (state.intents.has(intent)) state.intents.delete(intent);
  else state.intents.add(intent);
  document.querySelectorAll(".intent-toggle").forEach((button) => {
    button.classList.toggle("active", state.intents.has(button.dataset.intent));
  });
  updateIntentPill();
  $("#prompt").focus();
}

function scrollFeed() {
  const feed = $("#feed");
  if (feed) feed.scrollTop = feed.scrollHeight;
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
  sendPrompt($("#prompt").value);
});

$("#prompt").addEventListener("input", resizePrompt);
$("#prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendPrompt($("#prompt").value);
  }
});

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view || "panel"));
});
document.querySelectorAll("[data-intent]").forEach((button) => {
  button.addEventListener("click", () => toggleIntent(button.dataset.intent || ""));
});

$("#searchButton").addEventListener("click", () => {
  setView("chat");
  $("#prompt").value = "Search for ";
  $("#prompt").focus();
  resizePrompt();
});
$("#newChatButton").addEventListener("click", async () => {
  state.messages = [];
  await json("/api/command", { method: "POST", body: JSON.stringify({ command: "clear" }) });
  setView("chat");
});
$("#activityButton").addEventListener("click", () => toggleActivity());
$("#coreButton").addEventListener("click", () => toggleActivity());
$("#closeActivityButton").addEventListener("click", () => toggleActivity(false));
$("#approveButton").addEventListener("click", () => answerApproval(true));
$("#denyButton").addEventListener("click", () => answerApproval(false));

startAmbient();
refresh().then(poll);
