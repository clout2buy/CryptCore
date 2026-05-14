const state = { seq: 0 };

const $ = (selector) => document.querySelector(selector);

function eventText(event) {
  if (event.text) return event.text;
  if (event.error) return event.error;
  if (event.snapshot) {
    return `${event.snapshot.provider} / ${event.snapshot.model}`;
  }
  if (event.prompt) return event.prompt;
  return JSON.stringify(event, null, 2);
}

function addEvent(event) {
  if (event.seq) state.seq = Math.max(state.seq, Number(event.seq));
  const template = $("#eventTemplate").content.cloneNode(true);
  template.querySelector(".event-kind").textContent = event.event || "event";
  template.querySelector(".event-text").textContent = eventText(event);
  const feed = $("#feed");
  feed.appendChild(template);
  feed.scrollTop = feed.scrollHeight;
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

function renderStats(snapshot) {
  const rows = {
    workspace: snapshot.workspace,
    engine: `${snapshot.provider} / ${snapshot.model}`,
    auth: snapshot.auth,
    approval: snapshot.approval,
    tools: snapshot.tools,
    lessons: snapshot.lessons,
    skills: snapshot.skills,
    active: snapshot.activeTask || "none",
    autonomy: (snapshot.autonomy || []).length,
  };
  $("#runtimeStats").innerHTML = Object.entries(rows)
    .map(([key, value]) => `<dt>${key}</dt><dd>${String(value)}</dd>`)
    .join("");
}

function item(title, body = "") {
  const node = document.createElement("article");
  node.className = "item";
  node.innerHTML = `<b></b><span></span>`;
  node.querySelector("b").textContent = title;
  node.querySelector("span").textContent = body;
  return node;
}

function renderList(selector, rows, empty) {
  const el = $(selector);
  el.innerHTML = "";
  if (!rows.length) {
    el.appendChild(item(empty));
    return;
  }
  rows.forEach((row) => el.appendChild(row));
}

async function refresh() {
  const snapshot = await json("/api/snapshot");
  renderStats(snapshot);
  renderList(
    "#goals",
    (snapshot.goals || []).map((goal) => item(goal.title, `${goal.status} · P${goal.priority}`)),
    "No goals yet"
  );
  renderList(
    "#lessons",
    (snapshot.lessonsPreview || []).map((lesson) => item(lesson.text, `${lesson.scope} · ${lesson.confidence}`)),
    "No lessons yet"
  );
  renderList(
    "#reflections",
    (snapshot.reflections || []).map((reflection) => item(reflection.summary, reflection.reflection_id)),
    "No reflections yet"
  );
}

async function poll() {
  try {
    const data = await json(`/api/events?since=${state.seq}`);
    (data.events || []).forEach(addEvent);
    await refresh();
  } catch (error) {
    addEvent({ event: "webuiError", text: error.message });
  } finally {
    setTimeout(poll, 1200);
  }
}

$("#promptForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("#prompt").value.trim();
  if (!text) return;
  $("#prompt").value = "";
  addEvent({ event: "you", text });
  try {
    await json("/api/prompt", {
      method: "POST",
      body: JSON.stringify({ text, route: $("#route").value }),
    });
  } catch (error) {
    addEvent({ event: "sendFailed", text: error.message });
  }
});

$("#goalForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    await json("/api/goals", {
      method: "POST",
      body: JSON.stringify({
        title: form.get("title"),
        successMetric: form.get("successMetric"),
        priority: 4,
      }),
    });
    event.currentTarget.reset();
    await refresh();
  } catch (error) {
    addEvent({ event: "goalFailed", text: error.message });
  }
});

$("#lessonForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    await json("/api/lessons", {
      method: "POST",
      body: JSON.stringify({ text: form.get("text"), tags: ["webui"] }),
    });
    event.currentTarget.reset();
    await refresh();
  } catch (error) {
    addEvent({ event: "lessonFailed", text: error.message });
  }
});

$("#reflectButton").addEventListener("click", async () => {
  try {
    const data = await json("/api/reflect", { method: "POST", body: JSON.stringify({ limit: 5 }) });
    addEvent({ event: "reflect", text: `${(data.reflections || []).length} reflection(s) created` });
    await refresh();
  } catch (error) {
    addEvent({ event: "reflectFailed", text: error.message });
  }
});

$("#autonomyButton").addEventListener("click", async () => {
  try {
    const data = await json("/api/autonomy", { method: "POST", body: JSON.stringify({ limit: 5 }) });
    addEvent({ event: "autonomy", text: (data.cycle.notes || []).join("\n") });
    await refresh();
  } catch (error) {
    addEvent({ event: "autonomyFailed", text: error.message });
  }
});

$("#forgeButton").addEventListener("click", async () => {
  try {
    const data = await json("/api/forge", {
      method: "POST",
      body: JSON.stringify({ topic: $("#forgeTopic").value, minLessons: 1 }),
    });
    addEvent({ event: "skillForged", text: `${data.skillName} -> ${data.path}` });
  } catch (error) {
    addEvent({ event: "forgeFailed", text: error.message });
  }
});

refresh().then(poll);
