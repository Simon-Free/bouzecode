// [desc] Vue Coûts & tours du panneau d'un agent : coût par modèle (appels annexes compris), tableau par appel LLM (Δ, tokens, cache, coût, outils), détail d'un tour (payload annoté caché / écrit au cache / plein tarif). Les totaux sont ceux servis par l'API, jamais une somme faite ici. [/desc]
//
// Aucun symbole monétaire : les tarifs du serveur mélangent encore des devises
// (docs/refonte_ui/tokens_audit.md §5.1). On affiche donc « unités du tarif ».

import { api, h, skeleton, failed } from "../../lib/ui.js";
import { refreshButton } from "./view_tools.js";

const COST_UNIT = "unités du tarif";
const ESTIMATED_HINT = "estimée : l'API n'a pas renvoyé le compte de tokens de sortie";
const INPUT_ESTIMATED_HINT = "estimée : l'API n'a pas renvoyé le compte de tokens d'entrée (flux coupé avant l'usage), calculée sur la taille du prompt envoyé";
const STATUS_TONE = { cached: "ok", "new-cache": "info", fresh: "warn" };
const LEGEND = "caché = relu depuis le cache (le moins cher) · écrit au cache = mis en cache à cet appel (un peu plus cher que le plein tarif) · plein tarif = ni lu ni écrit";

const fmtTok = (n) => (n == null ? "—" : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
const fmtCost = (n) => (n == null ? "—" : Number(n).toFixed(4));
const num = (text, extra = "") => h("td", { class: `num${extra}` }, text);

function table(headers, rows) {
  return h("table", { class: "ag-table" },
    h("thead", {}, h("tr", {}, ...headers.map((x) => h("th", { scope: "col" }, x)))),
    h("tbody", {}, ...rows));
}

/** Sortie : « ~ » et infobulle quand elle est estimée. */
function outputCell(tokens, estimated, hint = ESTIMATED_HINT) {
  if (!estimated) return num(fmtTok(tokens));
  return h("td", { class: "num is-estimated", title: hint }, `~${fmtTok(tokens)}`);
}

/** Entrée : même marquage que la sortie quand l'usage n'est jamais arrivé. */
const inputCell = (tokens, estimated) => outputCell(tokens, estimated, INPUT_ESTIMATED_HINT);

// ---------------------------------------------------------------- coût par modèle

function modelRow(label, s, cls) {
  return h("tr", cls ? { class: cls } : {}, h("td", {}, label),
    num(String(s.calls)), num(s.side_calls ? `+${s.side_calls}` : "—"),
    inputCell(s.input_tokens, !!s.input_estimated_calls), outputCell(s.output_tokens, !!s.output_estimated_calls),
    num(fmtTok(s.cache_read_tokens)), num(fmtTok(s.cache_write_tokens)),
    num(`${s.cache_hit_pct}%`), num(s.unpriced ? "sans tarif" : fmtCost(s.cost)));
}

function costsByModel(costs) {
  const total = costs && costs.total;
  if (!total) return [h("p", { class: "ag-muted" }, "Pas encore de coût enregistré pour cet agent.")];
  const rows = Object.entries(costs.models || {}).map(([model, s]) => modelRow(model || "modèle inconnu", s));
  rows.push(modelRow("Total", total, "is-total"));
  const notes = [
    total.side_calls ? `Appels annexes (résumé de réflexion, classifieur, rattrapage, compaction) : ${total.side_calls}, inclus dans les totaux.` : "",
    total.output_estimated_calls ? `Sortie estimée sur ${total.output_estimated_calls} appel(s) (« ~ ») : l'API n'a pas renvoyé le compte.` : "",
    total.input_estimated_calls ? `Entrée estimée sur ${total.input_estimated_calls} appel(s) (« ~ ») : flux coupé avant le compte d'usage.` : "",
    costs.note || "",
  ].filter(Boolean);
  return [h("h3", {}, "Coût par modèle"),
    table(["Modèle", "Appels", "Annexes", "Entrée", "Sortie", "Cache lu", "Cache écrit", "% cache", `Coût (${COST_UNIT})`], rows),
    ...notes.map((n) => h("p", { class: "ag-muted" }, n))];
}

// ---------------------------------------------------------------- sous-agents

/** « Total avec sous-agents » + une ligne par sous-agent (servi par l'API, rien n'est sommé ici). */
function costsWithSubagents(costs) {
  const subs = (costs && costs.sous_agents) || [];
  if (!subs.length) return [];
  const rows = subs.map((s) => h("tr", {}, h("td", {}, s.titre || s.agent_id), num(String(s.calls)),
    num(s.unpriced ? "sans tarif" : fmtCost(s.cost))));
  return [
    h("p", { class: "ag-costs__total-tree" }, h("strong", {}, "Total avec sous-agents : "),
      `${fmtCost(costs.total_avec_sous_agents)} ${COST_UNIT} (${subs.length} sous-agent${subs.length > 1 ? "s" : ""})`),
    h("details", { class: "ag-costs__subs" }, h("summary", {}, "Détail par sous-agent"),
      table(["Sous-agent", "Appels", `Coût (${COST_UNIT})`], rows)),
  ];
}

// ---------------------------------------------------------------- détail d'un tour

function payloadItem(it) {
  return h("details", { class: `ag-payload ag-payload--${it.cache_status || "fresh"}` },
    h("summary", {},
      h("span", { class: "badge", "data-tone": STATUS_TONE[it.cache_status] || "warn" }, it.cache_label || it.cache_status || ""),
      h("span", { class: "ag-payload__kind" }, it.kind || ""),
      h("span", { class: "ag-payload__label" }, it.label || ""),
      h("span", { class: "ag-muted" }, `${fmtTok(it.est_tokens)} tok (estimé)`)),
    h("pre", { class: "code" }, it.content || it.preview || "(aperçu vide)"));
}

function turnSummary(d, estimated) {
  const out = `${estimated ? "~" : ""}${fmtTok(d.output_tokens)}`;
  return `entrée ${fmtTok(d.input_tokens)} (cache lu ${fmtTok(d.cache_read)}, écrit ${fmtTok(d.cache_create)}) · sortie ${out}`;
}

async function turnDetail(entry, call, box, row) {
  box.hidden = false;
  box.replaceChildren(h("p", { class: "ag-muted", role: "status" }, h("span", { class: "spinner spinner--sm" }), ` Chargement du tour ${call.turn}…`));
  row.setAttribute("aria-busy", "true");
  try {
    const d = await api("GET", `/api/sessions/${entry.key}/turns/${call.turn}`, undefined, { timeout: 60000 });
    if (d.error) throw new Error(d.error);
    const resp = h("div", { class: "ag-payload__response" });
    resp.innerHTML = d.response_html || "";
    box.replaceChildren(
      h("h3", {}, `Tour ${d.turn} — ${d.wire_message_count} messages envoyés`),
      h("p", { class: "ag-muted" }, turnSummary(d, call.output_estimated)),
      h("p", { class: "ag-muted ag-payload__legend" }, LEGEND),
      ...(d.items || []).map(payloadItem), h("h3", {}, "Réponse du modèle"), resp);
    box.scrollIntoView({ block: "nearest" });
  } catch (err) {
    failed(box, err, () => turnDetail(entry, call, box, row), { title: `Impossible de charger le tour ${call.turn}.` });
  } finally {
    row.removeAttribute("aria-busy");
  }
}

// ---------------------------------------------------------------- tours

function lienEnquete(entry, tour) {
  const agent = String(entry.key || "").replace(/^agent\//, "");
  const cible = `/enquete/${encodeURIComponent(agent)}${tour != null ? `#tour-${tour}` : ""}`;
  return h("a", { href: cible, class: "ag-enquete-lien", title: "Enquêter sur ce tour : diff, cache, note, saturation",
    onclick: (e) => e.stopPropagation() }, tour != null ? "Enquêter" : "Ouvrir l'enquête complète");
}

function turnRow(entry, c, detail) {
  const tr = h("tr", { tabindex: "0", class: "ag-table__clickable" },
    num(String(c.turn)), h("td", {}, c.time || ""),
    num(c.delta_s == null ? "—" : String(c.delta_s), c.delta_s > 60 ? " is-warn" : ""),
    inputCell(c.input_tokens, c.input_estimated), outputCell(c.output_tokens, c.output_estimated),
    num(fmtTok(c.cache_read)), num(fmtTok(c.cache_create)),
    num(`${c.cache_hit_pct}%`, c.cache_hit_pct < 50 ? " is-warn" : ""),
    num(fmtCost(c.cost)), h("td", {}, (c.tools || []).join(", ")),
    h("td", {}, lienEnquete(entry, c.turn)));
  const open = () => turnDetail(entry, c, detail, tr);
  tr.addEventListener("click", open);
  tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  return tr;
}

function turnsIntro(turns) {
  const side = turns.side_calls || { count: 0, cost: 0 };
  const parts = [`Prompt système ≈ ${fmtTok(turns.system_prompt_tokens)} tokens`,
    `coût total ${fmtCost(turns.total_cost)} (${COST_UNIT})`];
  if (side.count) parts.push(`dont + ${side.count} appel${side.count > 1 ? "s" : ""} annexe${side.count > 1 ? "s" : ""} (${fmtCost(side.cost)}) sans ligne ci-dessous`);
  parts.push(turns.missing_dumps ? "détail des payloads indisponible (dumps absents)" : "clique un tour pour voir le payload envoyé");
  return h("p", { class: "ag-muted ag-costs__intro" }, parts.join(" · "));
}

function turnsSection(entry, turns) {
  const calls = (turns && turns.calls) || [];
  const out = [h("h3", {}, "Appels au modèle, tour par tour")];
  if (turns && turns.note) out.push(h("p", { class: "ag-muted" }, turns.note));
  if (!calls.length) return out.concat(h("p", { class: "ag-muted" }, "Aucun appel enregistré."));
  const detail = h("div", { class: "ag-turn-detail", hidden: true });
  const enquete = turns.missing_dumps ? [] : [h("p", {}, lienEnquete(entry, null))];
  return out.concat(turnsIntro(turns), ...enquete,
    table(["Tour", "Heure", "Δ s", "Entrée", "Sortie", "Cache lu", "Cache écrit", "% cache", `Coût (${COST_UNIT})`, "Outils", ""],
      calls.map((c) => turnRow(entry, c, detail))),
    detail);
}

export function createCostsView(entry, pane) {
  const tools = h("div", { class: "ag-view__tools" });
  const body = h("div", { class: "ag-view__body ag-costs" });
  pane.append(tools, body);
  let loaded = false;

  async function load() {
    skeleton(body, 6);
    try {
      const [costs, turns] = await Promise.all([
        api("GET", `/api/sessions/${entry.key}/costs?avec_sous_agents=1`, undefined, { timeout: 60000 }),
        api("GET", `/api/sessions/${entry.key}/turns`, undefined, { timeout: 60000 }),
      ]);
      loaded = true;
      tools.replaceChildren(refreshButton("Actualiser", load));
      body.replaceChildren(...costsWithSubagents(costs), ...costsByModel(costs), ...turnsSection(entry, turns));
      body.removeAttribute("aria-busy");
    } catch (err) {
      failed(body, err, load, { title: "Impossible de charger les coûts." });
    }
  }
  return {
    show() { if (!loaded) load(); },
    maybeRefresh() {},
  };
}
