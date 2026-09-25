const elements = {
  health: document.querySelector("#health-status"),
  list: document.querySelector("#incident-list"),
  listState: document.querySelector("#list-state"),
  detail: document.querySelector("#incident-detail"),
  detailState: document.querySelector("#detail-state"),
  template: document.querySelector("#incident-template"),
  refresh: document.querySelector("#refresh"),
  openCount: document.querySelector("#open-count"),
  resolvedCount: document.querySelector("#resolved-count"),
  totalCount: document.querySelector("#total-count"),
};

let incidents = [];
let selectedId = null;

function text(value) {
  return value === null || value === undefined || value === "" ? "Not available" : String(value);
}

function timestamp(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? text(value) : date.toLocaleString();
}

function renderSummary() {
  elements.openCount.textContent = incidents.filter((incident) => incident.status === "firing").length;
  elements.resolvedCount.textContent = incidents.filter((incident) => incident.status === "resolved").length;
  elements.totalCount.textContent = incidents.length;
}

function renderList() {
  elements.list.replaceChildren();
  if (!incidents.length) {
    elements.listState.textContent = "No incidents have been created yet. Generate traffic and run a supported chaos scenario to demonstrate the pipeline.";
    return;
  }
  elements.listState.textContent = "";
  for (const incident of incidents) {
    const card = elements.template.content.firstElementChild.cloneNode(true);
    card.classList.toggle("resolved", incident.status === "resolved");
    card.classList.toggle("selected", incident.id === selectedId);
    card.querySelector(".alert-name").textContent = text(incident.alert_name);
    card.querySelector(".incident-meta").textContent = `${text(incident.severity)} | ${text(incident.service)} | ${timestamp(incident.updated_at)}`;
    card.addEventListener("click", () => selectIncident(incident.id));
    elements.list.append(card);
  }
}

function detailSection(title, content) {
  const section = document.createElement("section");
  section.className = "detail-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading, content);
  return section;
}

function jsonDetails(title, value) {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = title;
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(value || {}, null, 2);
  details.append(summary, pre);
  return details;
}

function renderDetail(incident) {
  elements.detail.replaceChildren();
  elements.detailState.textContent = "";
  const header = document.createElement("header");
  header.className = "detail-header";
  const title = document.createElement("div");
  title.className = "detail-title";
  const h2 = document.createElement("h2");
  h2.textContent = text(incident.alert_name);
  const badge = document.createElement("span");
  badge.className = `badge ${text(incident.status)}`;
  badge.textContent = text(incident.status);
  title.append(h2, badge);
  const metadata = document.createElement("div");
  metadata.className = "metadata";
  metadata.textContent = `Incident ${incident.id} | ${text(incident.severity)} | ${text(incident.service)} | ${text(incident.namespace)} | Started ${timestamp(incident.started_at)}`;
  header.append(title, metadata);

  const hypotheses = document.createElement("div");
  for (const item of incident.hypotheses || []) {
    const block = document.createElement("article");
    block.className = "hypothesis";
    const heading = document.createElement("h4");
    heading.textContent = text(item.type).replaceAll("_", " ");
    const description = document.createElement("p");
    description.textContent = text(item.description);
    const meta = document.createElement("div");
    meta.className = "hypothesis-meta";
    meta.textContent = `Confidence: ${Math.round(Number(item.confidence || 0) * 100)}%`;
    block.append(heading, description, meta);
    if (Array.isArray(item.recommended_actions) && item.recommended_actions.length) {
      const actions = document.createElement("ul");
      actions.className = "actions";
      item.recommended_actions.forEach((action) => {
        const row = document.createElement("li");
        row.textContent = action;
        actions.append(row);
      });
      block.append(actions);
    }
    if (item.runbook) {
      const link = document.createElement("a");
      link.className = "runbook";
      link.href = item.runbook;
      link.textContent = "Open associated runbook";
      block.append(link);
    }
    hypotheses.append(block);
  }
  if (!hypotheses.childElementCount) hypotheses.textContent = "No ranked hypotheses are available for this incident.";

  const evidence = document.createElement("div");
  const evidenceData = incident.evidence || {};
  ["prometheus", "loki", "tempo_analysis", "kubernetes", "gitops"].forEach((source) => {
    evidence.append(jsonDetails(`${source} evidence`, evidenceData[source]));
  });
  elements.detail.append(header, detailSection("Ranked hypotheses", hypotheses), detailSection("Evidence", evidence), detailSection("Raw alert", jsonDetails("Alertmanager payload", incident.payload)));
}

async function selectIncident(id) {
  selectedId = id;
  renderList();
  elements.detailState.textContent = "Loading incident details...";
  elements.detail.replaceChildren();
  try {
    const response = await fetch(`/incidents/${id}`);
    if (!response.ok) throw new Error(`Incident request failed (${response.status})`);
    renderDetail(await response.json());
  } catch (error) {
    elements.detailState.textContent = `Unable to load incident details: ${error.message}`;
  }
}

async function loadIncidents() {
  elements.listState.textContent = "Loading incidents...";
  try {
    const response = await fetch("/incidents");
    if (!response.ok) throw new Error(`Incident request failed (${response.status})`);
    incidents = await response.json();
    renderSummary();
    renderList();
    if (selectedId && !incidents.some((incident) => incident.id === selectedId)) {
      selectedId = null;
      elements.detail.replaceChildren();
      elements.detailState.textContent = "Select an incident to investigate.";
    }
  } catch (error) {
    elements.listState.textContent = `Unable to load incidents: ${error.message}`;
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/healthz");
    if (!response.ok) throw new Error();
    elements.health.textContent = "Correlator healthy";
  } catch {
    elements.health.textContent = "Correlator unavailable";
  }
}

elements.refresh.addEventListener("click", loadIncidents);
checkHealth();
loadIncidents();
setInterval(loadIncidents, 10000);
