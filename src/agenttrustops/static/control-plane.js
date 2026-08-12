"use strict";

let bearerToken = "";
let runs = [];
let selectedRunId = "";
let activeFilter = "all";
let noticeTimer = 0;

const byId = (id) => document.getElementById(id);
const controls = ["approve", "reject", "resume", "provider-reconcile", "reconcile"].map(byId);

function setConnected(connected) {
  const state = byId("connection-state");
  state.dataset.state = connected ? "online" : "offline";
  state.querySelector("output").textContent = connected ? "Authenticated" : "Disconnected";
}

function notify(message, isError = false) {
  const node = byId("notice");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.add("visible");
  window.clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(() => node.classList.remove("visible"), 4200);
}

async function api(path, options = {}) {
  if (!bearerToken) throw new Error("Connect with a scoped credential first.");
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${bearerToken}`);
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {...options, headers, cache: "no-store"});
  let payload = null;
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) {
    if (response.status === 401) setConnected(false);
    throw new Error(payload.detail || `Request failed (${response.status})`);
  }
  return payload;
}

function statusCount(status) {
  return runs.filter((run) => run.status === status).length;
}

function renderSummary() {
  byId("count-pending").textContent = String(statusCount("pending_approval"));
  byId("count-approved").textContent = String(statusCount("approved"));
  byId("count-unknown").textContent = String(statusCount("unknown"));
  byId("count-completed").textContent = String(statusCount("completed"));
}

function createRunCard(run) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "run-card";
  button.dataset.runId = String(run.run_id);
  button.setAttribute("aria-current", String(run.run_id === selectedRunId));

  const badge = document.createElement("span");
  badge.className = `badge ${String(run.status || "")}`;
  badge.textContent = String(run.status || "unknown").replaceAll("_", " ");
  const action = document.createElement("strong");
  action.textContent = String(run.action_name || "Unnamed action");
  const id = document.createElement("span");
  id.className = "run-id";
  id.textContent = String(run.run_id || "—");
  button.append(badge, action, id);
  button.addEventListener("click", () => selectRun(String(run.run_id)));
  return button;
}

function renderRuns() {
  const list = byId("run-list");
  list.replaceChildren();
  const filtered = activeFilter === "all" ? runs : runs.filter((run) => run.status === activeFilter);
  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = bearerToken ? "No runs match this filter." : "Connect with a viewer credential to load runs.";
    list.append(empty);
    return;
  }
  filtered.forEach((run) => list.append(createRunCard(run)));
}

function selectRun(runId) {
  selectedRunId = runId;
  const run = runs.find((item) => String(item.run_id) === runId);
  if (!run) return;
  byId("decision-title").textContent = String(run.action_name || "Governed run");
  const values = [run.status, run.action_name, run.run_id, run.policy_version];
  byId("run-details").querySelectorAll("dd").forEach((node, index) => {
    node.textContent = String(values[index] ?? "—");
  });
  byId("approve").disabled = run.status !== "pending_approval";
  byId("reject").disabled = run.status !== "pending_approval";
  byId("resume").disabled = run.status !== "approved";
  byId("provider-reconcile").disabled = run.status !== "unknown";
  byId("reconcile").disabled = run.status !== "unknown";
  renderRuns();
}

async function refresh() {
  try {
    const payload = await api("/v1/runs?limit=200");
    runs = Array.isArray(payload.runs) ? payload.runs : [];
    setConnected(true);
    renderSummary();
    renderRuns();
    if (selectedRunId) selectRun(selectedRunId);
  } catch (error) {
    notify(error.message, true);
  }
}

function note() {
  const value = byId("decision-note").value.trim();
  if (value.length < 3) throw new Error("Add an operator note of at least 3 characters.");
  return value;
}

async function runOperation(operation) {
  if (!selectedRunId) return notify("Select a run first.", true);
  try {
    let body;
    let path = `/v1/runs/${encodeURIComponent(selectedRunId)}/${operation}`;
    if (operation === "approve" || operation === "reject") body = JSON.stringify({note: note()});
    if (operation === "reconcile") body = JSON.stringify({note: note(), outcome: byId("reconcile-outcome").value, result: null});
    if (operation === "provider-reconcile") path = `/v1/runs/${encodeURIComponent(selectedRunId)}/reconcile-from-provider`;
    controls.forEach((control) => { control.disabled = true; });
    const payload = await api(path, {method: "POST", body});
    notify(`${operation}: ${payload.status}`);
    byId("decision-note").value = "";
    await refresh();
  } catch (error) {
    notify(error.message, true);
    selectRun(selectedRunId);
  }
}

byId("connect-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const tokenInput = byId("token");
  bearerToken = tokenInput.value.trim();
  tokenInput.value = "";
  await refresh();
});

byId("disconnect").addEventListener("click", () => {
  bearerToken = "";
  runs = [];
  selectedRunId = "";
  setConnected(false);
  renderSummary();
  renderRuns();
  controls.forEach((control) => { control.disabled = true; });
  notify("Credential cleared from memory.");
});

byId("refresh").addEventListener("click", refresh);
document.querySelectorAll(".filter").forEach((button) => {
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    document.querySelectorAll(".filter").forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    renderRuns();
  });
});
["approve", "reject", "resume", "provider-reconcile", "reconcile"].forEach((operation) => {
  byId(operation).addEventListener("click", () => runOperation(operation));
});
controls.forEach((control) => { control.disabled = true; });
