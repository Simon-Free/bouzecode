// [desc] Fil de session PARTAGÉ entre la page Agents (panneau à onglets) et le Bureau (tiroir de l'assistant) : insertion des blocs rendus par le serveur, heures locales, streaming token par token, et un fil autonome mono-session (startSessionThread) pour les surfaces sans onglets. [/desc]
//
// Ce module ne dépend de RIEN dans conversations/ ni bureau/ : il ne connaît qu'un conteneur
// DOM. API publique : appendBlocks, renderStreamingPartial, hydrateEventTimes (page Agents) ;
// startSessionThread({key, container, onStatus, onError}) → {stop, reveiller} (Bureau).

import { hydrateEventTimes } from "../time_format.js";
import { api } from "../lib/ui.js";

export { hydrateEventTimes };

const ACTIVE_STATES = new Set(["running", "awaiting_input", "awaiting_plan_validation"]);

/** Encart affiché dans un fil ENCORE VIDE (session pas encore écrite, agent qui démarre…). */
function setEmptyState(container, msg) {
  const kids = [...container.children];
  if (kids.some((el) => !el.classList.contains("conv-empty-state"))) return;
  let el = kids.find((n) => n.classList.contains("conv-empty-state"));
  if (!el) {
    el = document.createElement("div");
    el.className = "conv-empty-state";
    container.appendChild(el);
  }
  if (el.textContent !== msg) el.textContent = msg;
}

function waitingMessage(state) {
  if (state === "starting") return "Démarrage de l'agent…";
  return ACTIVE_STATES.has(state) ? "En attente de contenu…" : "Aucun contenu (session vide ou introuvable).";
}

const squash = (text) => String(text || "").replace(/\s+/g, "");
const echoText = (el) => (el.querySelector(".bz-echo__txt, .ag-echo__text") || el).textContent;

/** De vrais blocs arrivent : l'affichage PROVISOIRE (streaming, encart vide) est retiré, ainsi que
 *  l'écho de CHAQUE message de l'utilisateur qui vient d'arriver (`userTexts`). Retirer seulement
 *  la 1re bulle laissait en double le 2e message envoyé coup sur coup. Sans message reconnu (rendu
 *  markdown, troncature), la plus ancienne bulle part, comme avant. */
function purgeProvisional(container, userTexts) {
  container.querySelectorAll(".conv-empty-state, .streaming-turn, .streaming-block, .streaming-thinking, .streaming-tool").forEach((el) => el.remove());
  const echoes = [...container.querySelectorAll(".optimistic-echo")];
  let matched = 0;
  for (const text of userTexts) {
    const i = echoes.findIndex((el) => squash(text).includes(squash(echoText(el)).slice(0, 80)));
    if (i >= 0) { echoes.splice(i, 1)[0].remove(); matched++; }
  }
  if (!matched && echoes.length) echoes[0].remove();
}

// Le fil est-il « collé » en bas ? (si oui on suit la génération, sinon on respecte la
// position de lecture de l'utilisateur)
const isPinned = (c) => c.scrollTop + c.clientHeight >= c.scrollHeight - 40;
const scrollToEnd = (c) => { c.scrollTop = c.scrollHeight; };

// ---------------------------------------------------------------- groupes de tours
//
// Entre deux messages de l'utilisateur, TOUT ce que produit le modèle (texte, réflexion,
// outils, résultats, réponse finale, notices) vit dans UN seul groupe `.turn-group` : une
// bulle, et une fine ligne `hr.turn-sep` entre deux tours du modèle, au lieu d'une bulle par
// tour. Le groupe courant est toujours le DERNIER enfant du fil : un message de l'utilisateur
// (ou un écho, une question insérée par l'appelant) le referme de fait.

const isUserBlock = (el) => el.nodeType === 1 && el.classList.contains("block") && el.classList.contains("user");
const isModelTurn = (el) => el.nodeType === 1 && el.classList.contains("block") && el.classList.contains("assistant");
/** Enfant DIRECT portant la classe `cls` (sélecteur « scope » évité : inconnu de certains DOM de test). */
const directChild = (host, cls) => [...host.children].find((el) => el.classList.contains(cls)) || null;

/** Groupe du modèle ouvert en fin de fil, créé s'il n'y en a pas. */
function openGroup(container) {
  const last = container.lastElementChild;
  if (last && last.classList.contains("turn-group")) return last;
  const group = document.createElement("div");
  group.className = "turn-group";
  container.appendChild(group);
  return group;
}

/** Un groupe vidé (streaming purgé) en fin de fil ne doit pas s'intercaler avant un message de l'utilisateur. */
function dropTrailingEmptyGroup(container) {
  const last = container.lastElementChild;
  if (last && last.classList.contains("turn-group") && !last.firstElementChild) last.remove();
}

function placeNode(container, el) {
  if (el.nodeType !== 1) return;
  if (isUserBlock(el)) { dropTrailingEmptyGroup(container); container.appendChild(el); return; }
  const group = openGroup(container);
  if (isModelTurn(el) && [...group.children].some(isModelTurn)) {
    const sep = document.createElement("hr");
    sep.className = "turn-sep";
    group.appendChild(sep);
  }
  group.appendChild(el);
}

/** Insère les blocs rendus par le serveur (regroupés par tours du modèle) et hydrate leurs heures ; true si des blocs ont été insérés. */
export function appendBlocks(container, blocks) {
  const list = blocks || [];
  const tpl = document.createElement("template");
  const nodes = list.flatMap((b) => {
    tpl.innerHTML = b.html || "";
    return [...tpl.content.childNodes];
  });
  if (list.length) purgeProvisional(container, nodes.filter(isUserBlock).map((el) => el.textContent));
  nodes.forEach((el) => placeNode(container, el));
  hydrateEventTimes(container);
  return list.length > 0;
}

// ---------------------------------------------------------------- lecture incrémentale
//
// `after=N` suppose que les N premiers messages de la session ne bougent plus. C'est faux après
// une interruption : le tour coupé est gardé comme message ÉPHÉMÈRE (`_interrupted`), que la
// reprise RETIRE de la session. Le message suivant prend son index : `after=nextIndex` le
// sautait, et le fil perdait le message envoyé juste après « Interrompre » (et sa réponse).
// On relit donc toujours le DERNIER message déjà affiché : s'il n'est plus identique (ou si la
// session a raccourci), le fil a été réécrit et on le relit en entier.

/** Curseur d'une lecture incrémentale : index du prochain message + rendu du dernier affiché. */
export function newCursor() { return { nextIndex: 0, lastHtml: "" }; }

/** Retire du conteneur ce que le serveur y a rendu (blocs, groupes de tours, encart vide) ;
 *  les éléments propres à l'appelant (échos, questions…) restent. */
export function clearServerBlocks(container) {
  [...container.children].forEach((el) => {
    if (el.classList.contains("block") || el.classList.contains("turn-group") || el.classList.contains("conv-empty-state")) el.remove();
  });
}

/**
 * Lit les blocs nouveaux depuis `cursor` avec `get(after)` (promesse de la réponse /blocks).
 * → {data, blocks, reset} : `reset` = le fil a été réécrit côté serveur, `blocks` le contient
 * alors EN ENTIER (l'appelant vide d'abord son conteneur avec `clearServerBlocks`).
 */
export async function readNewBlocks(cursor, get) {
  if (!cursor.nextIndex) {
    const data = await get(0);
    return { data, blocks: (data && data.blocks) || [], reset: false };
  }
  const data = await get(cursor.nextIndex - 1);
  const list = (data && data.blocks) || [];
  if ((data.total || 0) >= cursor.nextIndex && list.length && list[0].html === cursor.lastHtml) {
    return { data, blocks: list.slice(1), reset: false };
  }
  const full = await get(0);
  return { data: full, blocks: (full && full.blocks) || [], reset: true };
}

/** Avance le curseur après insertion des blocs de `data` (`blocks` : ceux qui viennent d'être lus). */
export function advanceCursor(cursor, data, blocks) {
  const total = (data && data.total) || 0;
  const last = (blocks || []).find((b) => b.idx === total - 1);
  if (last) cursor.lastHtml = last.html || "";
  else if (!total) cursor.lastHtml = "";
  cursor.nextIndex = total;
}

// ---------------------------------------------------------------- streaming

function child(host, cls, build, before) {
  let el = directChild(host, cls);
  if (el) return el;
  el = document.createElement("div");
  el.className = cls;
  build(el);
  host.insertBefore(el, before || null);
  return el;
}

/** Tour en cours de production : il s'écrit DANS le groupe du modèle, comme le bloc qui le remplacera. */
function streamingTurn(container) {
  const existing = container.querySelector(".streaming-turn");
  if (existing) return existing;
  const turn = document.createElement("div");
  turn.className = "streaming-turn";
  openGroup(container).appendChild(turn);
  return turn;
}

/** Réflexion en cours : bloc repliable, ouvert pendant la réflexion puis replié dès le texte. */
function paintThinking(host, phase, thinking) {
  if (!thinking) { host.querySelector(".streaming-thinking")?.remove(); return; }
  const stk = child(host, "streaming-thinking", (el) => {
    el.innerHTML = '<div class="st-head"><span class="st-spinner"></span><span class="st-label"></span></div><div class="st-body"></div>';
    el.firstChild.addEventListener("click", () => el.classList.toggle("collapsed"));
  });
  const active = phase === "thinking";
  stk.querySelector(".st-label").textContent = active ? "Réflexion en cours…" : "Réflexion";
  stk.classList.toggle("collapsed", !active);
  stk.classList.toggle("thinking-active", active);
  const body = stk.querySelector(".st-body");
  if (body.textContent !== thinking) body.textContent = thinking;
}

/** « Outil en cours : X », détecté dans le texte partiel (dernier <tool_use name="X">). */
function paintTool(host, phase, text) {
  const names = [...text.matchAll(/<tool_use\s+name="([^"]+)"/g)];
  if (phase !== "text" || !names.length) { host.querySelector(".streaming-tool")?.remove(); return; }
  const tool = child(host, "streaming-tool", (el) => {
    el.innerHTML = '<span class="st-spinner"></span><span class="st-tool-label"></span>';
  }, directChild(host, "streaming-block"));
  tool.querySelector(".st-tool-label").textContent = `Outil en cours : ${names[names.length - 1][1]}`;
}

/** Texte de l'assistant qui grandit token par token. */
function paintText(host, phase, text) {
  if (phase !== "text" || !text) { host.querySelector(".streaming-block")?.remove(); return; }
  const sb = child(host, "streaming-block", () => {});
  if (sb.textContent !== text) sb.textContent = text;
}

/** Retire le tour provisoire (et son groupe s'il ne contenait que lui). */
function clearStreaming(container) {
  const turn = container.querySelector(".streaming-turn");
  if (!turn) return;
  const group = turn.parentElement;
  turn.remove();
  if (group && group.classList.contains("turn-group") && !group.firstElementChild) group.remove();
}

/** Rend l'état partiel {phase, text, thinking} d'un tour en cours ; `{}` efface tout l'affichage provisoire. */
export function renderStreamingPartial(container, data) {
  const phase = data.phase || "text";
  const text = data.text || "";
  const thinking = data.thinking || "";
  if (!text && !thinking) { clearStreaming(container); return; }
  const host = streamingTurn(container);
  paintThinking(host, phase, thinking);
  paintTool(host, phase, text);
  paintText(host, phase, text);
}

// ---------------------------------------------------------------- fil autonome

/** Délai avant la prochaine lecture : 1,5 s si l'agent est actif ou démarre (5 s onglet caché),
 *  15 s sinon. « starting » compte : relancé par un message, l'agent réécrit son fil. */
function nextDelay(state, fastUntil = 0) {
  if (!ACTIVE_STATES.has(state) && state !== "starting" && Date.now() >= fastUntil) return 15000;
  return document.visibilityState === "hidden" ? 5000 : 1500;
}

/**
 * Fil d'UNE session dans UN conteneur (tiroir de l'assistant du Bureau) : /blocks puis
 * /partial (250 ms) tant que l'agent écrit. `onStatus(status, total, data)` à chaque lecture
 * (l'appelant écrit SON libellé) ; `onError(err)` quand la lecture échoue.
 */
export function startSessionThread({ key, container, onStatus, onError }) {
  const run = { cursor: newCursor(), state: "", fastUntil: 0, polling: false, timer: null, partialTimer: null, streaming: false, stopped: false };
  const get = (after) => api("GET", `/api/sessions/${key}/blocks?after=${after}`, undefined, { timeout: 30000 });

  async function readBlocks() {
    const { data, blocks, reset } = await readNewBlocks(run.cursor, get);
    // Fil arrêté pendant la lecture (autre conversation ouverte) : rien de l'ancien fil ne s'insère.
    if (run.stopped) return;
    const pinned = isPinned(container);
    if (reset) clearServerBlocks(container);
    if (appendBlocks(container, blocks) || reset) {
      advanceCursor(run.cursor, data, blocks);
      if (pinned) scrollToEnd(container);
    }
    run.state = (data.status && data.status.state) || "cli";
    if (!run.cursor.nextIndex) setEmptyState(container, waitingMessage(run.state));
    if (typeof onStatus === "function") onStatus(data.status || {}, data.total || 0, data);
  }

  async function poll() {
    // Garde de réentrance : deux lectures du même `after=` inséreraient les blocs deux fois.
    if (run.stopped || run.polling) return;
    run.polling = true;
    try {
      await readBlocks();
    } catch (err) {
      // Réseau / 5xx : on retentera au prochain cycle ; l'appelant est prévenu pour le dire.
      if (typeof onError === "function") onError(err);
      else console.warn("fil de session : lecture impossible", err.message);
    } finally { run.polling = false; }
    if (run.stopped) return;
    clearTimeout(run.timer);
    run.timer = setTimeout(poll, nextDelay(run.state, run.fastUntil));
    if (run.state === "running" && !run.streaming && document.visibilityState !== "hidden") { run.streaming = true; pollPartial(); }
  }

  async function pollPartial() {
    if (run.stopped) return;
    try {
      const data = await api("GET", `/api/sessions/${key}/partial`, undefined, { timeout: 10000 });
      if (run.stopped) return;
      const pinned = isPinned(container);
      renderStreamingPartial(container, data || {});
      if (pinned) scrollToEnd(container);
    } catch (err) {
      console.warn("streaming interrompu", err.message);
    }
    if (run.stopped) return;
    if (run.state === "running" && document.visibilityState !== "hidden") { run.partialTimer = setTimeout(pollPartial, 250); return; }
    // Sortie de « running » / onglet caché : on purge l'affichage partiel, sinon un « Outil en cours : X » reste orphelin.
    renderStreamingPartial(container, {});
    run.streaming = false;
    run.partialTimer = null;
  }

  poll();
  return {
    stop() {
      run.stopped = true;
      clearTimeout(run.timer);
      clearTimeout(run.partialTimer);
      run.streaming = false;
    },
    /** Après un envoi : ne pas attendre la fin du délai courant, et relire vite pendant 20 s —
     *  l'agent oisif met quelques secondes à repartir, son état reste « idle » entre-temps. */
    reveiller() {
      run.fastUntil = Date.now() + 20000;
      clearTimeout(run.timer);
      run.timer = setTimeout(poll, 200);
    },
  };
}
