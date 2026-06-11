// [desc] Page projet: tickets kanban (dnd terminé/rouvrir), résultats MR, validations, commentaires, agents. [/desc]
"use strict";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function post(url, body) {
  const response = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await response.json();
  if (data.error) { alert(data.error); return null; }
  return data;
}

async function loadModels() {
  const { models } = await (await fetch("/api/models")).json();
  document.querySelectorAll(".model-select").forEach((select) => {
    select.appendChild(new Option("modèle (défaut)", ""));
    models.forEach((model) => select.appendChild(new Option(model.name, model.name)));
  });
}

async function loadTypologies() {
  const { typologies } = await (await fetch(`/api/typologies?project=${PROJECT_SLUG}`)).json();
  document.querySelectorAll(".typology-select").forEach((select) => {
    select.replaceChildren();
    typologies.forEach((t) => select.appendChild(new Option(t.description || t.name, t.name)));
  });
}

function selectedModel() {
  const select = document.querySelector(".model-select");
  return select ? select.value : "";
}

function selectedTypology() {
  const select = document.querySelector(".typology-select");
  return select ? select.value : "";
}

document.getElementById("t-classify").addEventListener("click", async () => {
  const prompt = document.getElementById("t-prompt").value.trim();
  if (!prompt) { alert("prompt requis pour déduire"); return; }
  const btn = document.getElementById("t-classify");
  btn.disabled = true; btn.textContent = "…";
  try {
    const result = await post("/api/classify", { prompt, project_slug: PROJECT_SLUG });
    if (result) {
      if (result.title) document.getElementById("t-title").value = result.title;
      if (result.typology) {
        const sel = document.querySelector(".typology-select");
        if (sel) sel.value = result.typology;
      }
    }
  } finally { btn.disabled = false; btn.textContent = "✨ Déduire"; }
});

document.getElementById("t-create").addEventListener("click", async () => {
  const title = document.getElementById("t-title").value.trim();
  const prompt = document.getElementById("t-prompt").value.trim();
  if (!title || !prompt) { alert("titre et prompt requis"); return; }
  const body = { title, prompt, model: selectedModel(), typology: selectedTypology(), launch: true };
  if (await post(`/api/projects/${PROJECT_SLUG}/tickets`, body))
    window.location.reload();
});

async function loadResults(card, container) {
  const response = await fetch(`/api/tickets/${PROJECT_SLUG}/${card.dataset.tid}/results`);
  const data = await response.json();
  container.replaceChildren();
  container.classList.remove("muted");
  data.mr_links.forEach((url) => {
    const link = el("a", "mr-link");
    link.href = url; link.target = "_blank"; link.textContent = url;
    container.appendChild(link);
  });
  if (!data.mr_links.length) container.appendChild(el("div", "muted", "aucune MR détectée dans la session"));
  if (data.branch) container.appendChild(el("div", "muted", `branche : ${data.branch}`));
  data.commits.forEach((commit) => container.appendChild(el("div", "commit-line", commit)));
  if (data.files.count) {
    const link = el("a", "mr-link", `${data.files.count} fichiers modifiés → voir les diffs`);
    link.href = `/sessions/${data.files.session_key}`;
    container.appendChild(link);
  }
}

document.querySelectorAll(".ticket").forEach((card) => {
  const base = `/api/tickets/${PROJECT_SLUG}/${card.dataset.tid}`;
  card.querySelector(".t-done").addEventListener("click", async () => {
    if (await post(`${base}/done`)) window.location.reload();
  });
  card.querySelector(".t-launch").addEventListener("click", async () => {
    if (await post(`${base}/launch`, { model: selectedModel() })) window.location.reload();
  });
  card.querySelectorAll(".t-validate").forEach((button) =>
    button.addEventListener("click", async () => {
      if (await post(`${base}/validate`, { kind: button.dataset.kind, model: selectedModel() }))
        window.location.reload();
    }));
  const commentInput = card.querySelector(".t-comment-text");
  const sendComment = async (send) => {
    const text = commentInput.value.trim();
    if (!text) return;
    if (await post(`${base}/comments`, { text, send })) window.location.reload();
  };
  card.querySelector(".t-comment").addEventListener("click", () => sendComment(false));
  card.querySelector(".t-comment-send").addEventListener("click", () => sendComment(true));

  const resultsDetails = card.querySelector(".t-results");
  let resultsLoaded = false;
  resultsDetails.addEventListener("toggle", () => {
    if (resultsDetails.open && !resultsLoaded) {
      resultsLoaded = true;
      loadResults(card, resultsDetails.querySelector(".results-body"));
    }
  });

  // DnD: seuls terminé ↔ autres colonnes sont des actions (les autres statuts sont dérivés)
  card.addEventListener("dragstart", (event) => {
    event.dataTransfer.setData("text/plain", JSON.stringify({
      tid: card.dataset.tid, from: card.closest(".kanban-col").dataset.status,
    }));
  });
});

document.querySelectorAll(".kanban-col").forEach((column) => {
  column.addEventListener("dragover", (event) => event.preventDefault());
  column.addEventListener("drop", async (event) => {
    event.preventDefault();
    const { tid, from } = JSON.parse(event.dataTransfer.getData("text/plain"));
    const to = column.dataset.status;
    const togglesDone = (to === "terminé") !== (from === "terminé");
    if (!togglesDone || from === to) return;
    if (await post(`/api/tickets/${PROJECT_SLUG}/${tid}/done`)) window.location.reload();
  });
});

const STATE_LABELS = { running: "en cours", awaiting_input: "question posée", finished: "terminé" };

async function refreshAgents() {
  const response = await fetch(`/api/projects/${PROJECT_SLUG}/agents`);
  if (!response.ok) return;
  const { agents } = await response.json();
  const container = document.getElementById("agents-list");
  container.replaceChildren();
  if (!agents.length) container.appendChild(el("p", "muted", "Aucun agent sur ce projet."));
  agents.slice(0, 12).forEach((agent) => {
    const card = el("a", "card");
    card.href = `/sessions/${agent.key}`;
    card.appendChild(el("span", `badge st-${agent.status.state}`, STATE_LABELS[agent.status.state] || agent.status.state));
    card.appendChild(el("div", "card-title", agent.title));
    card.appendChild(el("div", "muted", `${agent.model || "défaut"} · ${agent.started_at}`));
    container.appendChild(card);
  });
}

loadModels();
loadTypologies();
refreshAgents();
setInterval(refreshAgents, 3000);
