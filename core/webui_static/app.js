const state = {
  seq: 0,
  busy: false,
  activeApproval: null,
  messages: new Map(),
  activityOpen: false,
  selectedSurface: "chat",
  intents: new Set(),
  animationStarted: false,
};

const $ = (selector) => document.querySelector(selector);

function textFrom(event) {
  if (event.text) return String(event.text);
  if (event.error) return String(event.error);
  if (event.snapshot) return `${event.snapshot.provider} / ${event.snapshot.model}`;
  if (event.prompt) return String(event.prompt);
  return JSON.stringify(event, null, 2);
}

function setStatus(text) {
  $("#statusLine").textContent = text;
}

function hideWelcome() {
  $("#welcome").classList.add("hidden");
}

function scrollFeed() {
  const feed = $("#feed");
  feed.scrollTop = feed.scrollHeight;
}

function messageKey(id, role) {
  return `${role}:${id || crypto.randomUUID()}`;
}

function createMessage({ id, role, label, text = "", typing = false }) {
  hideWelcome();
  const key = messageKey(id, role);
  const node = document.createElement("article");
  node.className = `message ${role}${typing ? " typing" : ""}`;
  node.dataset.key = key;

  const labelNode = document.createElement("span");
  labelNode.className = "message-label";
  labelNode.textContent = label || (role === "user" ? "You" : "Crypt");

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  node.append(labelNode, bubble);
  $("#feed").appendChild(node);
  state.messages.set(key, { node, bubble, text });
  scrollFeed();
  return state.messages.get(key);
}

function upsertMessage({ id, role, label, text = "", append = false, typing = false }) {
  const key = messageKey(id, role);
  let record = state.messages.get(key);
  if (!record) record = createMessage({ id, role, label, text: "", typing });
  record.text = append ? record.text + text : text;
  record.bubble.textContent = record.text || (typing ? "Working on it." : "");
  record.node.classList.toggle("typing", typing);
  scrollFeed();
  return record;
}

function addUserMessage(text) {
  createMessage({ role: "user", label: "You", text });
}

function addSystemMessage(text) {
  createMessage({ role: "system", label: "Crypt", text });
}

function addActivity(title, body = "") {
  const item = document.createElement("article");
  item.className = "activity-item";
  const strong = document.createElement("strong");
  strong.textContent = title;
  const span = document.createElement("span");
  span.textContent = body;
  item.append(strong, span);
  const feed = $("#activityFeed");
  feed.prepend(item);
  while (feed.children.length > 80) feed.lastElementChild?.remove();
}

function renderCoreFeatures(features) {
  const container = $("#quietStats");
  container.innerHTML = "";
  for (const feature of features || []) {
    const card = document.createElement("article");
    card.className = "core-card";
    card.dataset.feature = feature.id || "";
    card.classList.toggle("active", feature.id === state.selectedSurface);
    card.title = feature.detail || "";

    const top = document.createElement("div");
    top.className = "core-card-top";

    const label = document.createElement("span");
    label.className = "core-label";
    label.textContent = feature.label || feature.id || "Core";

    const value = document.createElement("b");
    value.textContent = feature.value ?? "";

    const status = document.createElement("span");
    status.className = "core-status";
    status.textContent = feature.status || "";

    const detail = document.createElement("p");
    detail.textContent = feature.detail || "";

    top.append(label, value);
    card.append(top, status, detail);
    container.appendChild(card);
  }
}

function selectSurface(surface) {
  state.selectedSurface = surface || "chat";
  document.querySelectorAll(".surface-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.surface === state.selectedSurface);
  });
  if (state.selectedSurface === "chat") {
    toggleActivity(false);
    return;
  }
  toggleActivity(true);
  addActivity("Surface", `${state.selectedSurface} is ready behind chat.`);
  refresh();
}

function friendlyToolName(name) {
  const value = String(name || "tool");
  const map = {
    read_file: "Reading files",
    write_file: "Writing files",
    edit_file: "Editing files",
    shell: "Running a command",
    web_search: "Searching the web",
    fetch_url: "Opening a page",
    spawn_agent: "Delegating work",
  };
  return map[value] || value.replaceAll("_", " ");
}

function handleEvent(event) {
  if (event.seq) state.seq = Math.max(state.seq, Number(event.seq));
  const id = event.id || "default";

  switch (event.event) {
    case "snapshot":
      if (event.snapshot) renderSnapshot(event.snapshot);
      break;
    case "taskStarted":
      state.busy = true;
      setStatus("Working");
      upsertMessage({ id, role: "assistant", label: "Crypt", text: "", typing: true });
      addActivity("Started", event.prompt || "New request");
      break;
    case "taskProgress":
      setStatus("Working");
      addActivity(event.phase === "provider" ? "Engine ready" : "Working", textFrom(event));
      break;
    case "thinkingDelta":
      addActivity("Thinking", event.text || "");
      break;
    case "assistantDelta":
      upsertMessage({ id, role: "assistant", label: "Crypt", text: event.text || "", append: true, typing: true });
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
    case "autonomyQuiet":
      addActivity("Autonomy", event.text === "no autonomous changes needed" ? "Nothing new to update." : textFrom(event));
      break;
    case "autonomyError":
      addActivity("Autonomy paused", event.error || "");
      break;
    case "taskFinished":
      state.busy = false;
      setStatus("Ready");
      upsertMessage({
        id,
        role: "assistant",
        label: "Crypt",
        text: event.text || "Done.",
        typing: false,
      });
      if (event.snapshot) renderSnapshot(event.snapshot);
      addActivity("Finished", "Request complete");
      break;
    case "taskFailed":
      state.busy = false;
      setStatus("Needs attention");
      upsertMessage({
        id,
        role: "assistant",
        label: "Crypt",
        text: event.error || "Something failed.",
        typing: false,
      });
      if (event.snapshot) renderSnapshot(event.snapshot);
      addActivity("Stopped", event.error || "");
      break;
    case "commandResult":
      upsertMessage({ id, role: "assistant", label: "Crypt", text: textFrom(event), typing: false });
      addActivity("Command", event.command || "");
      break;
    case "error":
      state.busy = false;
      setStatus("Needs attention");
      addSystemMessage(event.error || "Something failed.");
      addActivity("Error", event.error || "");
      break;
    default:
      if (event.text || event.error) addActivity(event.event || "Event", textFrom(event));
      break;
  }
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

function renderSnapshot(snapshot) {
  if (!state.busy) setStatus(snapshot.activeTask ? "Working" : "Ready");
  $("#enginePill").textContent = `${snapshot.provider || "crypt"} / ${snapshot.model || "auto"}`;
  renderCoreFeatures(snapshot.coreFeatures || []);
}

async function refresh() {
  const snapshot = await json("/api/snapshot");
  renderSnapshot(snapshot);
}

async function poll() {
  try {
    const data = await json(`/api/events?since=${state.seq}`);
    (data.events || []).forEach(handleEvent);
    await refresh();
  } catch (error) {
    addActivity("WebUI", error.message);
  } finally {
    setTimeout(poll, 1000);
  }
}

async function sendPrompt(text) {
  const trimmed = text.trim();
  if (!trimmed || state.busy) return;
  $("#prompt").value = "";
  resizePrompt();
  addUserMessage(trimmed);
  state.busy = true;
  setStatus("Working");
  try {
    await json("/api/prompt", {
      method: "POST",
      body: JSON.stringify({ text: trimmed, intents: Array.from(state.intents) }),
    });
  } catch (error) {
    state.busy = false;
    setStatus("Needs attention");
    addSystemMessage(error.message);
  }
}

function updateIntentPill() {
  const intents = Array.from(state.intents);
  $("#intentPill").textContent = intents.length ? intents.join(" + ") : "autopilot";
}

function toggleIntent(intent) {
  if (!intent) return;
  if (state.intents.has(intent)) {
    state.intents.delete(intent);
  } else {
    state.intents.add(intent);
  }
  document.querySelectorAll(".intent-toggle").forEach((button) => {
    button.classList.toggle("active", state.intents.has(button.dataset.intent));
  });
  updateIntentPill();
  $("#prompt").focus();
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

function startAmbient() {
  if (state.animationStarted) return;
  state.animationStarted = true;
  const canvas = $("#ambient");
  const ctx = canvas.getContext("2d");
  const dots = Array.from({ length: 54 }, (_, index) => ({
    x: Math.random(),
    y: Math.random(),
    r: 1 + (index % 3) * .45,
    speed: .00035 + (index % 5) * .00008,
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
    ctx.globalAlpha = .18;
    ctx.strokeStyle = "#c8ff55";
    ctx.lineWidth = 1;
    for (let x = -80 + ((time * .018) % 80); x < width + 80; x += 80) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x + height * .28, height);
      ctx.stroke();
    }
    const pulse = .26 + Math.sin(time * .002) * .08;
    const glow = ctx.createRadialGradient(width * .5, height * .42, 0, width * .5, height * .42, Math.min(width, height) * .25);
    glow.addColorStop(0, `rgba(244, 163, 58, ${pulse})`);
    glow.addColorStop(.46, "rgba(244, 163, 58, .05)");
    glow.addColorStop(1, "rgba(244, 163, 58, 0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, width, height);
    ctx.globalAlpha = .9;
    for (const dot of dots) {
      dot.y = (dot.y + dot.speed) % 1;
      const x = dot.x * width;
      const y = dot.y * height;
      ctx.beginPath();
      ctx.fillStyle = dot.r > 1.5 ? "#69d9ff" : "#c8ff55";
      ctx.arc(x, y, dot.r, 0, Math.PI * 2);
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

$("#activityButton").addEventListener("click", () => toggleActivity());
$("#closeActivityButton").addEventListener("click", () => toggleActivity(false));
document.querySelectorAll("[data-surface]").forEach((button) => {
  button.addEventListener("click", () => selectSurface(button.dataset.surface || "chat"));
});
document.querySelectorAll("[data-intent]").forEach((button) => {
  button.addEventListener("click", () => toggleIntent(button.dataset.intent || ""));
});

$("#newChatButton").addEventListener("click", async () => {
  $("#feed").innerHTML = "";
  state.messages.clear();
  $("#welcome").classList.remove("hidden");
  addActivity("New conversation", "Session cleared");
  await json("/api/command", { method: "POST", body: JSON.stringify({ command: "clear" }) });
});

$("#approveButton").addEventListener("click", () => answerApproval(true));
$("#denyButton").addEventListener("click", () => answerApproval(false));

startAmbient();
refresh().then(poll);
