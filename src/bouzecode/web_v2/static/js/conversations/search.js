// Recherche plein-texte dans les conversations (GET /api/search), rendue au-dessus
// de la sidebar. Portée « Ouverts » ou « Tous » ; un résultat ouvre l'onglet ciblé.

import { node } from "./dom.js";
import { openTab } from "./panel/tabs.js";

// Bandeau des agents interrompus par le dernier arrêt serveur (snapshot figé au boot,
// exposé par GET /api/interrupted). NE relance RIEN automatiquement : l'utilisateur clique.
async function fetchJson(url, opts) {
  try {
    const resp = await fetch(url, opts);
    if (!resp.ok) return null;
    return await resp.json();
  } catch (_) {
    return null; // best-effort : ne bloque jamais l'affichage.
  }
}

let searchScope = "open";

export function wireSearch() {
  const list = document.getElementById("conv-list");
  if (!list || !list.parentNode) return;
  const box = document.createElement("div");
  box.className = "conv-search";
  const input = document.createElement("input");
  input.type = "search";
  input.id = "conv-search-input";
  input.className = "conv-search-input";
  input.placeholder = "Rechercher un mot-clé…";
  box.appendChild(input);
  const toggles = node(box, "div", "conv-search-scope");
  for (const [scope, label] of [["open", "Ouverts"], ["all", "Tous"]]) {
    const btn = node(toggles, "button", "conv-search-toggle", label);
    btn.type = "button";
    btn.dataset.scope = scope;
    if (scope === searchScope) btn.classList.add("active");
    btn.addEventListener("click", () => {
      searchScope = scope;
      for (const b of toggles.querySelectorAll(".conv-search-toggle")) {
        b.classList.toggle("active", b.dataset.scope === scope);
      }
      if (input.value.trim()) runSearch(input);
    });
  }
  const results = node(box, "div", "conv-search-results");
  results.id = "conv-search-results";
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); runSearch(input); }
  });
  list.parentNode.insertBefore(box, list);
}

async function runSearch(input) {
  const results = document.getElementById("conv-search-results");
  if (!results) return;
  results.textContent = "";
  const q = input.value.trim();
  if (!q) return;
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  let data;
  try {
    const resp = await fetch(
      `/api/search?q=${encodeURIComponent(q)}&scope=${searchScope}`);
    if (!resp.ok) throw new Error("http");
    data = await resp.json();
  } catch (_) {
    node(results, "p", "muted", "Erreur lors de la recherche.");
    return;
  }
  const rows = (data && data.results) || [];
  if (!rows.length) {
    node(results, "p", "muted", "Aucun résultat.");
    return;
  }
  for (const r of rows) {
    const item = node(results, "div", "conv-search-item");
    node(item, "div", "conv-search-title", r.ticket_title || r.agent_id);
    for (const m of r.matches || []) {
      const line = node(item, "div", "conv-search-match");
      node(line, "span", "conv-search-role",
        m.role === "user" ? "vous" : "réponse");
      renderSnippet(node(line, "span", "conv-search-snippet"), m.snippet, words);
    }
    item.addEventListener("click", () => {
      openTab(r.key, r.ticket_title || r.agent_id);
    });
  }
}

function renderSnippet(el, snippet, words) {
  const text = snippet || "";
  const low = text.toLowerCase();
  let idx = -1;
  let hitLen = 0;
  for (const w of words) {
    const p = low.indexOf(w);
    if (p !== -1 && (idx === -1 || p < idx)) { idx = p; hitLen = w.length; }
  }
  if (idx === -1) { el.textContent = text; return; }
  if (idx > 0) el.appendChild(document.createTextNode(text.slice(0, idx)));
  const mark = document.createElement("mark");
  mark.textContent = text.slice(idx, idx + hitLen);
  el.appendChild(mark);
  el.appendChild(document.createTextNode(text.slice(idx + hitLen)));
}
