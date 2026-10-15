// [desc] Boîte à outils UI partagée : appels API, boutons occupés, toasts, confirmation, états vide/erreur/chargement. [/desc]
//
// Toute page passe par ce module pour respecter les règles transverses de SPEC.md §2 :
//   geste → busy(btn)  → api()  → toast / erreur inline   (R1, R3, R4, R5)
//   chargement → skeleton(el) → rendu | failed(el, err, retry) | empty(el)   (R2, R4)
//
// Module ES. Il s'expose aussi sur `window.ui` et émet `ui:ready` sur `document` pour les
// scripts classiques (non-module) qui ne peuvent pas l'importer.
//
// Événements émis sur `window` :
//   ui:net  {detail:{ok:boolean}}  — chaque réponse (ok:true) ou échec réseau (ok:false) ;
//                                    écouté par lib/poll.js (détecteur « connexion perdue »).

import { parseInstant } from "../time_format.js";

// ---------------------------------------------------------------- utilitaires

/** Échappe une chaîne pour insertion dans du HTML. */
export function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/**
 * Petit constructeur DOM : h("button", {class:"btn", onclick: fn, "aria-label": "x"}, "texte", enfant).
 * Attributs : `class`, `text`, `html` (déconseillé), `dataset` (objet), `style` (objet),
 * `on<evt>` (écouteur), booléens (`hidden`, `disabled`), le reste via setAttribute.
 * Enfants : chaînes (nœuds texte), nœuds, tableaux, null/false ignorés.
 */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  appendChildren(el, children);
  return el;
}

function appendChildren(el, children) {
  for (const c of children) {
    if (c == null || c === false) continue;
    if (Array.isArray(c)) appendChildren(el, c);
    else el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

function pad(n) { return String(n).padStart(2, "0"); }

/**
 * Temps relatif en français : « à l'instant », « il y a 5 min », « il y a 3 h »,
 * « hier 14:05 », « 12/09 14:05 ». Chaîne vide si l'instant est invalide.
 */
export function relTime(iso, now = new Date()) {
  if (!iso) return "";
  const d = parseInstant(iso);
  if (!d) return "";
  const s = Math.round((now - d) / 1000);
  if (s < 45 && s > -45) return "à l'instant";
  if (s < 0) return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (s < 3600) return `il y a ${Math.max(1, Math.round(s / 60))} min`;
  const dayA = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dayB = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((dayB - dayA) / 86400000);
  if (days === 0) return `il y a ${Math.round(s / 3600)} h`;
  const hhmm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (days === 1) return `hier ${hhmm}`;
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${hhmm}`;
}

/** Heure locale « HH:MM » d'un instant (défaut : maintenant). */
export function hhmm(d = new Date()) {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ---------------------------------------------------------------- api()

/** Erreur levée par api() : `.status` (0 = réseau, -1 = délai), `.data` (corps JSON ou null), `.code`. */
export class ApiError extends Error {
  constructor(message, { status = 0, data = null, code = "" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
    this.code = code;
  }
}

/** Extrait un message lisible d'un corps d'erreur quelle que soit sa forme. */
export function errorMessage(data, status) {
  if (data && typeof data === "object") {
    const e = data.error;
    if (typeof e === "string" && e.trim()) return e.trim();
    if (e && typeof e === "object" && typeof e.message === "string" && e.message.trim()) return e.message.trim();
    for (const k of ["message", "detail", "reason"]) {
      if (typeof data[k] === "string" && data[k].trim()) return data[k].trim();
    }
    if (Array.isArray(data.errors) && data.errors.length) return data.errors.map(String).join(" ; ");
  }
  if (typeof data === "string" && data.trim() && data.length < 300 && !/^\s*</.test(data)) return data.trim();
  if (status === 404) return "Introuvable (404).";
  if (status === 409) return "Conflit : l'état a changé entre-temps (409).";
  if (status === 503) return "Service indisponible (503).";
  if (status >= 500) return `Erreur du serveur (${status}).`;
  return `Requête refusée (HTTP ${status}).`;
}

function emitNet(ok) {
  try { window.dispatchEvent(new CustomEvent("ui:net", { detail: { ok } })); } catch (_) { /* hors navigateur */ }
}

/** Le jeton local du serveur (spec ticketing B8), servi par base.html ; "" hors page. */
export function bouzecodeToken() {
  if (typeof document === "undefined" || !document.querySelector) return "";
  const meta = document.querySelector('meta[name="bouzecode-token"]');
  return (meta && meta.getAttribute("content")) || "";
}

/**
 * Appel JSON unique de l'application. Ne renvoie QUE sur succès ; sinon lève une ApiError
 * au message lisible (jamais « Uncaught (in promise) », jamais un 500 HTML pris pour un succès).
 *
 * @param {string} method  GET | POST | PATCH | PUT | DELETE
 * @param {string} url
 * @param {object|FormData|undefined} body  sérialisé en JSON sauf FormData
 * @param {{signal?:AbortSignal, timeout?:number, okField?:string|boolean, headers?:object}} [opts]
 *   timeout  : ms avant abandon (défaut 30000 ; 0 = aucun) → ApiError status -1
 *   okField  : si la réponse 2xx porte `data[okField] === false` (défaut du champ : "ok"),
 *              c'est une ERREUR (cas « HTTP 200 {ok:false} » interdit par R4).
 * @returns {Promise<any>} le JSON décodé (ou le texte si la réponse n'est pas du JSON, ou null si vide)
 */
export async function api(method, url, body, opts = {}) {
  const { signal, timeout = 30000, okField, headers = {} } = opts;
  const verb = (method || "GET").toUpperCase();
  const init = { method: verb, headers: { Accept: "application/json", ...headers } };
  // Toute mutation exige le jeton local (sinon 401 jeton_manquant).
  if (verb !== "GET" && verb !== "HEAD") {
    const token = bouzecodeToken();
    if (token) init.headers["X-Bouzecode-Token"] = token;
  }
  if (body !== undefined && body !== null) {
    if (typeof FormData !== "undefined" && body instanceof FormData) init.body = body;
    else { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
  }
  const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
  let timer = null;
  let timedOut = false;
  if (ctrl) {
    init.signal = ctrl.signal;
    if (signal) {
      if (signal.aborted) ctrl.abort();
      else signal.addEventListener("abort", () => ctrl.abort(), { once: true });
    }
    if (timeout > 0) timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, timeout);
  }
  let resp;
  try {
    resp = await fetch(url, init);
  } catch (e) {
    if (timer) clearTimeout(timer);
    if (timedOut) throw new ApiError(`Le serveur n'a pas répondu à temps (${Math.round(timeout / 1000)} s).`, { status: -1, code: "timeout" });
    if (signal && signal.aborted) throw new ApiError("Requête annulée.", { status: 0, code: "aborted" });
    emitNet(false);
    throw new ApiError("Serveur injoignable : vérifie qu'il tourne, puis réessaie.", { status: 0, code: "network" });
  }
  if (timer) clearTimeout(timer);
  emitNet(true);
  let data = null;
  if (typeof resp.text === "function") {
    let text = "";
    try { text = await resp.text(); } catch (_) { text = ""; }
    if (text) {
      try { data = JSON.parse(text); } catch (_) { data = text; }
    }
  } else if (typeof resp.json === "function") {
    // Réponses simulées minimales ({ok, json}) des tests : on accepte aussi cette forme.
    try { data = await resp.json(); } catch (_) { data = null; }
  }
  if (!resp.ok) {
    const code = data && typeof data === "object" && data.error && typeof data.error === "object"
      ? (data.error.code || "") : (data && typeof data === "object" ? (data.code || "") : "");
    throw new ApiError(errorMessage(data, resp.status), { status: resp.status, data, code });
  }
  if (okField) {
    const field = okField === true ? "ok" : okField;
    if (data && typeof data === "object" && data[field] === false) {
      throw new ApiError(errorMessage(data, resp.status) === `Requête refusée (HTTP ${resp.status}).`
        ? "L'opération a échoué." : errorMessage(data, resp.status), { status: resp.status, data, code: "not_ok" });
    }
  }
  return data;
}

// ---------------------------------------------------------------- busy()

const BUSY = new WeakMap();

/** Le bouton est-il en cours d'action (busy) ? */
export function isBusy(btn) { return !!(btn && BUSY.has(btn)); }

/**
 * Exécute `fn` en affichant le bouton comme occupé : désactivé, `aria-busy`, spinner et
 * libellé d'action (« Enregistrement… »). Restaure tout dans un finally. Un bouton déjà
 * occupé NE relance PAS fn (anti double-clic, R5) : la promesse résout alors `undefined`.
 * Les erreurs de fn sont propagées (à l'appelant d'afficher le toast).
 *
 * @param {HTMLElement|null} btn
 * @param {string|null} label  libellé pendant l'action (null = garder le libellé)
 * @param {() => any} fn
 */
export async function busy(btn, label, fn) {
  if (typeof label === "function") { fn = label; label = null; }
  if (btn && BUSY.has(btn)) return undefined;
  if (btn) {
    BUSY.set(btn, { html: btn.innerHTML, disabled: btn.disabled });
    btn.setAttribute("aria-busy", "true");
    if ("disabled" in btn) btn.disabled = true;
    else btn.setAttribute("aria-disabled", "true");
    if (label) btn.textContent = label;
  }
  try {
    return await fn();
  } finally {
    if (btn) {
      const saved = BUSY.get(btn);
      BUSY.delete(btn);
      btn.removeAttribute("aria-busy");
      btn.removeAttribute("aria-disabled");
      if (saved) {
        if (label) btn.innerHTML = saved.html;
        if ("disabled" in btn) btn.disabled = saved.disabled;
      }
    }
  }
}

/**
 * Verrouille un champ de saisie (readonly + aria-busy) pendant `fn` — pour Entrée dans un
 * champ : le focus et le texte restent, une seconde Entrée est ignorée (R5).
 */
export async function lock(field, fn) {
  if (field && BUSY.has(field)) return undefined;
  if (field) {
    BUSY.set(field, { readOnly: field.readOnly });
    field.readOnly = true;
    field.setAttribute("aria-busy", "true");
  }
  try {
    return await fn();
  } finally {
    if (field) {
      const saved = BUSY.get(field);
      BUSY.delete(field);
      field.readOnly = saved ? saved.readOnly : false;
      field.removeAttribute("aria-busy");
    }
  }
}

// ---------------------------------------------------------------- toasts

const TOAST_ICONS = { ok: "✓", err: "!", info: "i" };
const MAX_TOASTS = 5;

function toastStack() {
  let stack = document.getElementById("toasts");
  if (!stack) {
    stack = h("div", { id: "toasts", class: "toast-stack" });
    document.body.appendChild(stack);
  }
  return stack;
}

/**
 * Affiche un toast. Renvoie une poignée `{el, close()}`.
 * @param {"ok"|"err"|"info"} kind
 * @param {string} msg
 * @param {{action?:{label:string, fn:Function}, sticky?:boolean, timeout?:number}} [opts]
 *   Durées par défaut : ok/info 4 s, avec action 10 s, err = persistant (✕ pour fermer).
 */
function showToast(kind, msg, opts = {}) {
  const stack = toastStack();
  const sticky = opts.sticky != null ? opts.sticky : kind === "err";
  const timeout = opts.timeout != null ? opts.timeout : (opts.action ? 10000 : 4000);
  const el = h("div", {
    class: "toast", "data-kind": kind,
    role: kind === "err" ? "alert" : "status",
    "aria-live": kind === "err" ? "assertive" : "polite",
  });
  el.appendChild(h("span", { class: "toast__icon", "aria-hidden": "true" }, TOAST_ICONS[kind] || "i"));
  el.appendChild(h("span", { class: "toast__msg" }, msg));
  const actions = h("span", { class: "toast__actions" });
  let timer = null;
  const handle = {
    el,
    close() {
      if (timer) clearTimeout(timer);
      if (!el.isConnected) return;
      el.classList.add("toast--leaving");
      setTimeout(() => el.remove(), 180);
    },
  };
  if (opts.action && opts.action.label) {
    const b = h("button", { type: "button", class: "toast__action" }, opts.action.label);
    b.addEventListener("click", async () => {
      handle.close();
      try { await opts.action.fn(); } catch (e) { toast.err(e && e.message ? e.message : String(e)); }
    });
    actions.appendChild(b);
  }
  const close = h("button", { type: "button", class: "toast__close", "aria-label": "Fermer" }, "×");
  close.addEventListener("click", () => handle.close());
  actions.appendChild(close);
  el.appendChild(actions);
  stack.appendChild(el);
  while (stack.children.length > MAX_TOASTS) stack.firstChild.remove();
  if (!sticky && timeout > 0) timer = setTimeout(() => handle.close(), timeout);
  return handle;
}

export const toast = {
  ok: (msg, opts) => showToast("ok", msg, opts),
  err: (msg, opts) => showToast("err", msg && msg.message ? msg.message : msg, opts),
  info: (msg, opts) => showToast("info", msg, opts),
  /** Ferme tous les toasts (tests, changement de page). */
  clear() { const s = document.getElementById("toasts"); if (s) s.replaceChildren(); },
};

// ---------------------------------------------------------------- confirm()

/**
 * Dialogue de confirmation stylé (remplace window.confirm). Échap / « Annuler » / clic sur
 * le fond → false ; bouton de confirmation → true. Focus piégé dans le dialogue ; en mode
 * `danger`, le focus initial est sur « Annuler » (le geste sûr).
 * @param {{title:string, text?:string, confirmLabel?:string, cancelLabel?:string, danger?:boolean}} o
 * @returns {Promise<boolean>}
 */
export function confirm(o = {}) {
  const { title = "Confirmer ?", text = "", confirmLabel = "Confirmer", cancelLabel = "Annuler", danger = false } = o;
  return new Promise((resolve) => {
    const previous = document.activeElement;
    const titleId = `ui-dlg-t-${Math.random().toString(36).slice(2, 8)}`;
    const dlg = h("dialog", { class: "ui-dialog", "aria-labelledby": titleId, "aria-modal": "true" });
    const body = h("div", { class: "ui-dialog__body" },
      h("h2", { class: "ui-dialog__title", id: titleId }, title),
      text ? h("p", { class: "ui-dialog__text" }, text) : null);
    const cancelBtn = h("button", { type: "button", class: "btn", "data-role": "cancel" }, cancelLabel);
    const okBtn = h("button", { type: "button", class: `btn ${danger ? "btn--danger" : "btn--primary"}`, "data-role": "confirm" }, confirmLabel);
    dlg.append(body, h("div", { class: "ui-dialog__actions" }, cancelBtn, okBtn));
    document.body.appendChild(dlg);
    let done = false;
    const finish = (value) => {
      if (done) return;
      done = true;
      try { if (dlg.open && typeof dlg.close === "function") dlg.close(); } catch (_) { /* déjà fermé */ }
      dlg.remove();
      if (previous && typeof previous.focus === "function") previous.focus();
      resolve(value);
    };
    cancelBtn.addEventListener("click", () => finish(false));
    okBtn.addEventListener("click", () => finish(true));
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); finish(false); });
    dlg.addEventListener("click", (e) => { if (e.target === dlg) finish(false); });
    dlg.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); finish(false); return; }
      if (e.key === "Tab") {
        const f = [cancelBtn, okBtn];
        const i = f.indexOf(document.activeElement);
        e.preventDefault();
        f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
      }
    });
    if (typeof dlg.showModal === "function") {
      try { dlg.showModal(); } catch (_) { dlg.setAttribute("open", ""); }
    } else {
      dlg.setAttribute("open", "");
    }
    (danger ? cancelBtn : okBtn).focus();
  });
}

// ---------------------------------------------------------------- dirty()

function fieldsOf(root) {
  if (root.matches && root.matches("input,textarea,select")) return [root];
  return [...root.querySelectorAll("input,textarea,select")].filter((f) => f.type !== "button" && f.type !== "submit");
}

function snapshot(root) {
  return fieldsOf(root).map((f) => (f.type === "checkbox" || f.type === "radio" ? String(f.checked) : f.value)).join("\u0000");
}

/**
 * Suit les modifications non enregistrées d'un formulaire ou d'un champ (R9).
 * Pose `data-dirty="true"` sur l'élément, remplit `opts.flag` (« • modifié ») et arme une
 * garde `beforeunload` tant que c'est modifié.
 * @param {HTMLElement} root
 * @param {{onChange?:(dirty:boolean)=>void, flag?:HTMLElement, label?:string}} [opts]
 * @returns {{isDirty():boolean, markClean():void, check():boolean, guard(msg?:string):Promise<boolean>, destroy():void}}
 *   markClean() : l'état courant devient la référence (après un enregistrement réussi)
 *   guard()     : true s'il n'y a rien à perdre ou si l'utilisateur accepte d'abandonner
 */
export function dirty(root, opts = {}) {
  const { onChange, flag, label = "• modifié" } = opts;
  let reference = snapshot(root);
  let state = false;
  const apply = (value) => {
    if (value === state) return;
    state = value;
    root.dataset.dirty = value ? "true" : "false";
    if (flag) flag.textContent = value ? label : "";
    if (onChange) onChange(value);
  };
  const check = () => { apply(snapshot(root) !== reference); return state; };
  const onUnload = (e) => { if (state) { e.preventDefault(); e.returnValue = ""; } };
  root.addEventListener("input", check);
  root.addEventListener("change", check);
  window.addEventListener("beforeunload", onUnload);
  root.dataset.dirty = "false";
  return {
    isDirty: () => state,
    check,
    markClean() { reference = snapshot(root); apply(false); },
    async guard(msg) {
      if (!check()) return true;
      return confirm({ title: "Abandonner les modifications ?", text: msg || "Tes modifications non enregistrées seront perdues.",
        confirmLabel: "Abandonner", cancelLabel: "Continuer l'édition", danger: true });
    },
    destroy() {
      root.removeEventListener("input", check);
      root.removeEventListener("change", check);
      window.removeEventListener("beforeunload", onUnload);
    },
  };
}

// ---------------------------------------------------------------- états de zone

/** Remplace le contenu de `el` par un squelette de `n` lignes (chargement, R2). */
export function skeleton(el, n = 3) {
  if (!el) return;
  const sk = h("div", { class: "skeleton", "aria-hidden": "true" });
  for (let i = 0; i < n; i++) sk.appendChild(h("div", { class: "skeleton__line" }));
  el.replaceChildren(sk, h("span", { class: "sr-only", role: "status" }, "Chargement…"));
  el.setAttribute("aria-busy", "true");
}

/** Remplace le contenu de `el` par un état vide. `action` = {label, fn} optionnel. */
export function empty(el, { title = "Rien ici.", text = "", action = null, inline = false } = {}) {
  if (!el) return null;
  const box = h("div", { class: `empty${inline ? " empty--inline" : ""}` },
    h("div", { class: "empty__title" }, title),
    text ? h("div", { class: "empty__text" }, text) : null);
  if (action && action.label) {
    const b = h("button", { type: "button", class: "btn btn--sm" }, action.label);
    b.addEventListener("click", () => busy(b, null, action.fn));
    box.appendChild(b);
  }
  el.removeAttribute("aria-busy");
  el.replaceChildren(box);
  return box;
}

/**
 * Remplace le contenu de `el` par un état d'erreur + « Réessayer » (R4). Pendant le
 * réessai le bouton est occupé ; `retryFn` est responsable de re-remplir `el`.
 */
export function failed(el, err, retryFn, { title = "Impossible de charger." } = {}) {
  if (!el) return null;
  const msg = err && err.message ? err.message : (err ? String(err) : "");
  const box = h("div", { class: "error-state", role: "alert" },
    h("div", { class: "error-state__title" }, title),
    msg ? h("div", { class: "error-state__text" }, msg) : null);
  if (retryFn) {
    const b = h("button", { type: "button", class: "btn btn--sm" }, "Réessayer");
    b.addEventListener("click", () => busy(b, "Nouvel essai…", async () => { await retryFn(); }));
    box.appendChild(b);
  }
  el.removeAttribute("aria-busy");
  el.replaceChildren(box);
  return box;
}

/** Surligne `el` 2 s et le fait défiler dans la vue (résultat visible, R3). */
export function highlight(el) {
  if (!el) return;
  el.classList.remove("is-highlighted");
  void el.offsetWidth; // relance l'animation si déjà surligné
  el.classList.add("is-highlighted");
  if (typeof el.scrollIntoView === "function") {
    try { el.scrollIntoView({ block: "nearest", behavior: "smooth" }); } catch (_) { el.scrollIntoView(); }
  }
  setTimeout(() => el.classList.remove("is-highlighted"), 2000);
}

// ---------------------------------------------------------------- menu ⋯

let openMenu = null;

function closeOpenMenu(focusAnchor) {
  if (!openMenu) return;
  const { list, anchor, onDoc } = openMenu;
  list.remove();
  anchor.setAttribute("aria-expanded", "false");
  document.removeEventListener("pointerdown", onDoc, true);
  openMenu = null;
  if (focusAnchor) anchor.focus();
}

/**
 * Menu contextuel accessible (⋯) ancré sur `anchor` (un bouton déjà placé dans un
 * conteneur `.menu`, ou n'importe quel bouton : on l'enveloppe au besoin).
 * items : [{label, fn, danger?, disabled?, hint?} | "sep"] ou une fonction qui renvoie ce tableau
 * (évaluée à chaque ouverture). Flèches haut/bas, Entrée, Échap, clic extérieur.
 * Renvoie `{open(), close()}`.
 */
export function menu(anchor, items, { align = "right" } = {}) {
  anchor.setAttribute("aria-haspopup", "menu");
  anchor.setAttribute("aria-expanded", "false");
  if (!anchor.parentElement || !anchor.parentElement.classList.contains("menu")) {
    const wrap = h("span", { class: "menu" });
    anchor.replaceWith(wrap);
    wrap.appendChild(anchor);
  }
  const open = () => {
    closeOpenMenu(false);
    const list = h("div", { class: "menu__list", role: "menu", "data-align": align });
    const buttons = [];
    for (const it of (typeof items === "function" ? items() : items)) {
      if (!it) continue;
      if (it === "sep") { list.appendChild(h("div", { class: "menu__sep", role: "separator" })); continue; }
      const b = h("button", {
        type: "button", role: "menuitem", class: `menu__item${it.danger ? " menu__item--danger" : ""}`,
        disabled: !!it.disabled, title: it.hint || null,
      }, it.label);
      b.addEventListener("click", async (e) => {
        e.stopPropagation();
        closeOpenMenu(true);
        try { await it.fn(); } catch (err) { toast.err(err && err.message ? err.message : String(err)); }
      });
      buttons.push(b);
      list.appendChild(b);
    }
    list.addEventListener("keydown", (e) => {
      const enabled = buttons.filter((b) => !b.disabled);
      const i = enabled.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); enabled[(i + 1) % enabled.length]?.focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); enabled[(i - 1 + enabled.length) % enabled.length]?.focus(); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeOpenMenu(true); }
      else if (e.key === "Tab") { closeOpenMenu(false); }
    });
    anchor.parentElement.appendChild(list);
    anchor.setAttribute("aria-expanded", "true");
    const onDoc = (e) => { if (!list.contains(e.target) && e.target !== anchor) closeOpenMenu(false); };
    document.addEventListener("pointerdown", onDoc, true);
    openMenu = { list, anchor, onDoc };
    buttons.find((b) => !b.disabled)?.focus();
  };
  anchor.addEventListener("click", (e) => {
    e.stopPropagation();
    if (openMenu && openMenu.anchor === anchor) closeOpenMenu(true);
    else open();
  });
  anchor.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); open(); }
  });
  return { open, close: () => { if (openMenu && openMenu.anchor === anchor) closeOpenMenu(false); } };
}

// ---------------------------------------------------------------- exposition globale

export const ui = {
  api, ApiError, errorMessage, busy, isBusy, lock, toast, confirm, dirty, skeleton, empty, failed,
  highlight, menu, relTime, hhmm, escapeHtml, h,
};

if (typeof window !== "undefined") {
  window.ui = ui;
  try { document.dispatchEvent(new CustomEvent("ui:ready")); } catch (_) { /* hors navigateur */ }
}

export default ui;
