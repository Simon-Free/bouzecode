// [desc] Profils : aperçu EN DIRECT du prompt calculé (debounce 400 ms, requêtes obsolètes annulées, jamais périmé). [/desc]
import { api, h, skeleton, failed } from "../lib/ui.js";
import { estimateTokens, formatTokens } from "./state.js";

const $ = (id) => document.getElementById(id);
const DEBOUNCE_MS = 400;

let timer = null;
let inflight = null;
let generation = 0;
let getPayload = () => ({});
let hasContent = false;

/** `payloadFn` fournit la sélection courante (editor.collect). */
export function initPreview(payloadFn) {
  getPayload = payloadFn;
  skeleton($("pf-preview-body"), 8);
}

function setState(text, busy) {
  const el = $("pf-preview-state");
  el.textContent = text;
  $("pf-preview-body").classList.toggle("pf-preview__body--stale", !!busy && hasContent);
  $("pf-preview-body").setAttribute("aria-busy", busy ? "true" : "false");
}

/**
 * Planifie un recalcul. Dès la modification, l'aperçu affiché est marqué « mise à jour… »
 * (atténué) : il n'est JAMAIS présenté comme à jour alors qu'il ne l'est plus.
 */
export function schedulePreview({ immediate = false } = {}) {
  generation++;
  if (timer) clearTimeout(timer);
  if (inflight) { inflight.abort(); inflight = null; }
  setState("Mise à jour…", true);
  timer = setTimeout(run, immediate ? 0 : DEBOUNCE_MS);
}

async function run() {
  timer = null;
  const gen = generation;
  const ctrl = new AbortController();
  inflight = ctrl;
  if (!hasContent) skeleton($("pf-preview-body"), 8);
  let data;
  try {
    data = await api("POST", "/api/builder/preview", getPayload(), { signal: ctrl.signal, timeout: 20000 });
  } catch (err) {
    if (gen !== generation || err.code === "aborted") return; // remplacé par un calcul plus récent
    inflight = null;
    hasContent = false;
    setState("", false);
    $("pf-preview-meta").textContent = "";
    failed($("pf-preview-body"), err, async () => { schedulePreview({ immediate: true }); },
      { title: "Impossible de calculer l'aperçu." });
    return;
  }
  if (gen !== generation) return;
  inflight = null;
  render(data || {});
}

const pluriel = (n, mot, x = "s") => `${n} ${mot}${n > 1 ? x : ""}`;

/** Pastilles de taille : tokens estimés, outils, skills, garde-fous modifiés (détail en infobulle). */
function chips(prompt, r) {
  const tools = r.tools || [];
  const skills = r.skills || [];
  const hooks = r.hooks || [];
  return [
    h("span", { class: "chip" }, formatTokens(estimateTokens(prompt))),
    h("span", { class: "chip", title: tools.join(", ") }, `${pluriel(tools.length, "outil")} (schémas séparés)`),
    h("span", { class: "chip", title: skills.join(", ") }, `${pluriel(skills.length, "skill")} dans le prompt`),
    hooks.length ? h("span", { class: "chip", title: hooks.join(", ") },
      `${pluriel(hooks.length, "garde-fou", "x")} modifié${hooks.length > 1 ? "s" : ""}`) : null,
  ].filter(Boolean);
}

function render(data) {
  const prompt = data.system_prompt || "";
  $("pf-preview-meta").replaceChildren(...chips(prompt, data.runtime || {}));
  const pre = h("pre", { class: "pf-preview__prompt", id: "pf-preview-prompt", tabindex: "0",
    "aria-label": "Prompt système complet calculé" });
  pre.textContent = prompt;
  const note = h("p", { class: "pf-muted pf-preview__note" },
    "Les outils sont envoyés à part (schémas d'API) et les garde-fous agissent à l'exécution : ils n'apparaissent pas dans ce texte."
    + (data.custom_marker ? ` Tes instructions sont sous « ${data.custom_marker} ».` : ""));
  $("pf-preview-body").replaceChildren(pre, note);
  $("pf-preview-body").removeAttribute("aria-busy");
  hasContent = true;
  setState("À jour", false);
}
