// [desc] Recherche de la liste des agents : filtre instantané sur les agents chargés, et recherche plein texte dans les conversations (Entrée ou pause de frappe) avec état « Recherche… », « Aucun résultat » et effacement. [/desc]

import { api, h } from "../lib/ui.js";
import { emit } from "./store.js";
import { setFilter } from "./list.js";

const FULLTEXT_DELAY = 600;
const MIN_FULLTEXT = 3;

let input = null;
let clearBtn = null;
let results = null;
let timer = null;
let seq = 0;

function renderSnippet(snippet, words) {
  const text = snippet || "";
  const low = text.toLowerCase();
  let idx = -1;
  let len = 0;
  for (const w of words) {
    const p = low.indexOf(w);
    if (p !== -1 && (idx === -1 || p < idx)) { idx = p; len = w.length; }
  }
  if (idx === -1) return [text];
  return [text.slice(0, idx), h("mark", {}, text.slice(idx, idx + len)), text.slice(idx + len)];
}

function hideResults() {
  results.hidden = true;
  results.replaceChildren();
}

function stateLine(...children) {
  return h("p", { class: "ag-search-results__state", role: "status" }, ...children);
}

function showSearching(q) {
  results.hidden = false;
  results.setAttribute("aria-busy", "true");
  results.replaceChildren(stateLine(h("span", { class: "spinner spinner--sm", "aria-hidden": "true" }),
    ` Recherche de « ${q} » dans les conversations…`));
}

function showSearchError(q, err) {
  const retry = h("button", { type: "button", class: "btn btn--sm" }, "Réessayer");
  retry.addEventListener("click", () => fullText(q));
  results.replaceChildren(h("div", { class: "error-state error-state--inline", role: "alert" },
    h("span", {}, `Recherche impossible : ${err.message}`), retry));
}

function hit(r, words) {
  const match = (r.matches || [])[0];
  const b = h("button", { type: "button", class: "ag-search-hit" },
    h("span", { class: "ag-search-hit__title" }, r.ticket_title || r.agent_id || r.key),
    match ? h("span", { class: "ag-search-hit__snippet" },
      h("span", { class: "ag-search-hit__role" }, match.role === "user" ? "toi : " : "agent : "),
      ...renderSnippet(match.snippet, words)) : null);
  b.addEventListener("click", () => emit("open", { key: r.key, title: r.ticket_title }));
  return b;
}

function showHits(q, rows) {
  if (!rows.length) {
    results.replaceChildren(stateLine(`Aucune conversation ne contient « ${q} ».`));
    return;
  }
  const many = rows.length > 1;
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  results.replaceChildren(
    stateLine(`${rows.length} conversation${many ? "s" : ""} contien${many ? "nent" : "t"} « ${q} »`),
    h("div", { class: "ag-search-results__list" }, ...rows.slice(0, 30).map((r) => hit(r, words))));
}

async function fullText(q) {
  const my = ++seq;
  showSearching(q);
  let rows;
  try {
    const data = await api("GET", `/api/search?q=${encodeURIComponent(q)}&scope=all`, undefined, { timeout: 30000 });
    rows = (data && data.results) || [];
  } catch (err) {
    if (my !== seq) return;
    results.removeAttribute("aria-busy");
    showSearchError(q, err);
    return;
  }
  if (my !== seq) return;
  results.removeAttribute("aria-busy");
  showHits(q, rows);
}

function onInput() {
  const q = input.value.trim();
  clearBtn.hidden = !input.value;
  setFilter(q);
  clearTimeout(timer);
  seq++;
  if (q.length >= MIN_FULLTEXT) timer = setTimeout(() => fullText(q), FULLTEXT_DELAY);
  else hideResults();
}

export function clearSearch() {
  input.value = "";
  onInput();
}

export function wireSearch() {
  input = document.getElementById("ag-filter");
  clearBtn = document.getElementById("ag-filter-clear");
  results = document.getElementById("ag-search-results");
  if (!input || !clearBtn || !results) return;
  input.addEventListener("input", onInput);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      clearTimeout(timer);
      const q = input.value.trim();
      if (q) fullText(q);
    } else if (e.key === "Escape") {
      if (input.value) { e.preventDefault(); clearSearch(); } else input.blur();
    }
  });
  clearBtn.addEventListener("click", () => { clearSearch(); input.focus(); });
  // « / » place le focus dans la recherche (hors champ de saisie).
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    e.preventDefault();
    input.focus();
  });
}
