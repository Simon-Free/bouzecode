// [desc] Fil d'un agent : rafraîchissement de /blocks (rapide si l'onglet est actif et l'agent vivant, lent sinon), squelette au chargement, étapes de lancement, « ↓ Nouveaux messages », agent introuvable ou lancement échoué, et câblage streaming + question + champ de message. [/desc]

import { api, h, skeleton } from "../../lib/ui.js";
import { poller } from "../../lib/poll.js";
import { agentState, agentStateKey } from "../../lib/states.js";
import { emit, findNode, nodeForTicket, state as store } from "../store.js";
import { launchStepIndex, nodeState } from "../model.js";
import { appendBlocks, hydrateEventTimes, newCursor, readNewBlocks, advanceCursor, clearServerBlocks } from "../../shared/session_thread.js";
import { restoreKeys } from "../actions.js";
import { createQuestion } from "./question.js";
import { createComposer } from "./composer.js";
import { createStreaming } from "./streaming.js";
import { launchSteps, launchFailure, notFound, emptyConversation, loadError, pairToolBlocks } from "./thread_view.js";

const LAUNCH_STALL_MS = 120000;
/** Messages chargés à l'ouverture d'un agent, puis par clic sur « messages précédents » :
 *  une session de 78 Mo pesait 51 Mo de HTML et 5 à 10 s de rendu serveur d'un bloc. */
const PAGE = 80;
const MISSING_STATE = { key: "missing", label: "Introuvable", tone: "danger", icon: "!", group: "a_traiter", pulse: false, hint: "" };

/** État d'affichage d'après le statut servi par /blocks, complété par l'arbre (sous-agents vivants). */
function stateFromStatus(status, node) {
  if (node && node.etat === "archived") return agentState("archived");
  let key = agentStateKey({ state: status.state, liveness: status.liveness, phase: status.phase });
  if ((key === "finished" || key === "idle") && node && node.etat === "orchestrating") key = "orchestrating";
  return agentState(key);
}

/** Zone de messages défilante avec le bouton « ↓ Nouveaux messages ». */
function createScroller() {
  const conv = h("div", { class: "conv-messages ag-thread__msgs", role: "log", "aria-label": "Fil de la conversation" });
  const stateBox = h("div", { class: "ag-thread__state", hidden: true });
  const scroller = h("div", { class: "ag-thread" }, stateBox, conv);
  const newBtn = h("button", { type: "button", class: "btn btn--sm ag-thread__new", hidden: true }, "↓ Nouveaux messages");
  const pinned = () => scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 48;
  const toEnd = () => { scroller.scrollTop = scroller.scrollHeight; newBtn.hidden = true; };
  newBtn.addEventListener("click", toEnd);
  scroller.addEventListener("scroll", () => { if (pinned()) newBtn.hidden = true; });
  return {
    conv, stateBox, pinned, toEnd,
    frame: h("div", { class: "ag-thread__frame" }, scroller, newBtn),
    /** Du contenu est arrivé : on suit si l'on était en bas, sinon on propose d'y aller. */
    follow(wasPinned) { if (wasPinned) toEnd(); else newBtn.hidden = false; },
    showState(children) {
      stateBox.hidden = !children;
      stateBox.replaceChildren(...(children ? [].concat(children).filter(Boolean) : []));
    },
    hideNewIfAtEnd() { if (!newBtn.hidden && pinned()) newBtn.hidden = true; },
  };
}

export function createThread(entry, pane, hooks) {
  const view = createScroller();
  const { conv } = view;
  const composer = createComposer(entry, { conv: () => conv, scrollToEnd: view.toEnd, kick: () => kick() });
  const question = createQuestion({ answer: (label) => composer.deliver(label) });
  const streaming = createStreaming(entry, conv, {
    pinned: view.pinned,
    onText: (wasPinned) => { view.showState(null); view.follow(wasPinned); },
  });
  pane.append(view.frame, question.el, composer.el);
  const load = { cursor: newCursor(), first: true, launchSince: 0, debut: 0 };
  const olderBtn = h("button", { type: "button", class: "btn btn--sm ag-thread__older", hidden: true });
  olderBtn.addEventListener("click", () => loadOlder());
  let kickTimer = null;
  let stopped = false;

  // Liens vers des sous-agents rendus par le serveur (marqueurs « N agents lancés »).
  conv.addEventListener("click", (e) => {
    const el = e.target.closest("[data-open-key]");
    if (!el || !conv.contains(el)) return;
    e.preventDefault();
    emit("open", { key: el.getAttribute("data-open-key"), title: el.textContent.trim() });
  });

  function setState(info) {
    const changed = !entry.stateInfo || entry.stateInfo.key !== info.key;
    entry.stateInfo = info;
    if (!changed) return;
    hooks.repaintTab();
    // La liste suit le panneau : un changement d'état vu ici la rafraîchit aussitôt.
    if (entry.everSet) emit("refresh-tree");
    entry.everSet = true;
  }

  function showFailure(reason) {
    setState(agentState("launch_failed"));
    view.showState(launchFailure(reason));
    composer.update("launch_failed", []);
  }

  function showNotFound(err) {
    setState(MISSING_STATE);
    view.showState(notFound(err, async () => { await restoreKeys([entry.key], entry.title); restart(); }, () => hooks.close()));
    composer.update("missing", []);
    question.update(null, conv);
  }

  // ------------------------------------------------------------ onglet de lancement

  /** Le lancement a abouti ou échoué : l'onglet est rebranché sur la clé définitive. */
  function followLaunch(data, ticketId) {
    if (data.agent_key) { hooks.retarget(data.agent_key); return true; }
    if (!data.launch_failed) return false;
    entry.launchError = data.launch_error || "";
    hooks.retarget(`failed/${ticketId}`);
    return true;
  }

  /** /blocks ne connaît plus ce lancement : l'arbre dit ce qu'il est devenu, sinon on patiente. */
  function launchVanished(ticketId) {
    const node = nodeForTicket(ticketId);
    if (node) { hooks.retarget(node.key, node.title); return run(); }
    emit("refresh-tree");
    view.showState(launchSteps(2, "", Date.now() - load.launchSince > LAUNCH_STALL_MS));
    return { fast: true };
  }

  async function pollLaunching() {
    const ticketId = entry.key.slice("launching/".length);
    if (!load.launchSince) load.launchSince = Date.now();
    let data = null;
    try {
      data = await api("GET", `/api/sessions/${entry.key}/blocks`, undefined, { timeout: 20000 });
    } catch (err) {
      if (err.status !== 404) throw err;
    }
    if (!data) return launchVanished(ticketId);
    if (followLaunch(data, ticketId)) return run();
    const st = data.status || {};
    setState(agentState("preparing"));
    view.showState(launchSteps(launchStepIndex(st, true), [st.phase_label, st.phase_detail].filter(Boolean).join(" — ")));
    composer.update("preparing", []);
    return { fast: true };
  }

  // ------------------------------------------------------------ agent né

  async function fetchBlocks() {
    try {
      //  Lecture sûre même si le fil est réécrit (tour interrompu retiré à la reprise). Toute
      //  lecture depuis le début (ouverture, fil réécrit) ne prend que la dernière page.
      return await readNewBlocks(load.cursor, (after) =>
        api("GET", `/api/sessions/${entry.key}/blocks?after=${after}${after === 0 ? `&tail=${PAGE}` : ""}`, undefined, { timeout: 30000 }));
    } catch (err) {
      if (err.status === 404) { showNotFound(err); return null; }
      if (load.first) conv.replaceChildren(loadError(err));
      throw err;
    }
  }

  function showOlder(debut) {
    load.debut = debut;
    olderBtn.hidden = !(debut > 0);
    olderBtn.disabled = false;
    olderBtn.textContent = `↑ Messages précédents (${debut})`;
    if (debut > 0 && conv.firstChild !== olderBtn) conv.prepend(olderBtn);
    if (!(debut > 0)) olderBtn.remove();
  }

  /** Insère une page plus ancienne AVANT le fil affiché, sans faire sauter la lecture. */
  function prependOlder(blocks) {
    const tmp = document.createElement("div");
    appendBlocks(tmp, blocks);
    const anchor = olderBtn.nextElementSibling;
    const lastOld = tmp.lastElementChild;
    const isTurn = (el) => el.classList.contains("block") && el.classList.contains("assistant");
    // Un tour du modèle coupé par la pagination : ses deux moitiés reforment un seul groupe.
    if (anchor && lastOld && anchor.classList.contains("turn-group") && lastOld.classList.contains("turn-group")) {
      const firstTurn = [...anchor.children].find(isTurn);
      if (firstTurn && [...lastOld.children].some(isTurn)) firstTurn.before(h("hr", { class: "turn-sep" }));
      anchor.prepend(...lastOld.childNodes);
      lastOld.remove();
    }
    olderBtn.after(...tmp.childNodes);
  }

  async function loadOlder() {
    const fin = load.debut;
    if (!(fin > 0) || olderBtn.disabled) return;
    olderBtn.disabled = true;
    let data;
    try {
      data = await api("GET", `/api/sessions/${entry.key}/blocks?after=${Math.max(0, fin - PAGE)}&before=${fin}`, undefined, { timeout: 30000 });
    } catch {
      olderBtn.disabled = false;  // nouvel essai au prochain clic
      return;
    }
    const scroller = conv.parentElement;
    const before = scroller.scrollHeight;
    prependOlder(data.blocks || []);
    pairToolBlocks(conv);
    scroller.scrollTop += scroller.scrollHeight - before;
    showOlder(typeof data.debut === "number" ? data.debut : Math.max(0, fin - PAGE));
  }

  function appendNew({ data, blocks, reset }) {
    const wasPinned = view.pinned();
    const first = load.first;
    if (load.first) { conv.replaceChildren(); conv.removeAttribute("aria-busy"); load.first = false; }
    if (reset) clearServerBlocks(conv);
    if (first || reset) showOlder((data && data.debut) || 0);
    if (!appendBlocks(conv, blocks) && !reset) return;
    advanceCursor(load.cursor, data, blocks);
    pairToolBlocks(conv);
    view.follow(wasPinned);
    hooks.onUnread();
  }

  /** Corps encore vide : on dit POURQUOI (démarrage, attente du modèle, conversation vide). */
  function explainEmptyBody(info, status) {
    if (load.cursor.nextIndex || conv.querySelector(".streaming-block, .streaming-thinking, .ag-echo")) { view.showState(null); return; }
    view.showState(info.group === "en_cours" ? launchSteps(launchStepIndex(status, false), "") : emptyConversation());
  }

  async function pollAgent() {
    const polledAt = Date.now();  // une file lue AVANT un accusé 202 ne dit rien de ce message
    const cursor = load.cursor;
    const read = await fetchBlocks();
    if (!read || stopped) return { fast: false };
    //  Fil relancé pendant la lecture (Restaurer, nouvel essai) : cette lecture partait d'un index
    //  de l'ANCIEN fil ; l'insérer dans le fil vidé en perdrait le début. La relecture suit.
    if (cursor !== load.cursor) return { fast: true };
    appendNew(read);
    const { data } = read;
    const status = data.status || {};
    entry.status = status;
    entry.meta = data.meta || {};
    const info = stateFromStatus(status, findNode(entry.key));
    setState(info);
    explainEmptyBody(info, status);
    question.update(status, conv);
    composer.update(info.key, data.queue || [], polledAt);
    composer.reconcile(conv, info.key);
    hooks.onStatus();
    streaming.manage();
    return { fast: info.group === "en_cours" || (data.queue || []).some((q) => q.statut !== "non_livre") || composer.pending() };
  }

  async function run() {
    if (stopped) return { fast: false };
    if (entry.key.startsWith("failed/")) {
      const node = findNode(entry.key);
      showFailure((node && node.launch_error) || entry.launchError);
      hooks.onStatus();
      return { fast: false };
    }
    if (!entry.key.startsWith("launching/")) return pollAgent();
    const res = await pollLaunching();
    hooks.onStatus();
    return res;
  }

  const p = poller(run, { interval: 15000, fastInterval: 1500, isFast: (res) => !!(res && res.fast && entry.active), pauseWhenHidden: true });

  function kick() {
    p.fast(true);
    p.now();
    clearTimeout(kickTimer);
    kickTimer = setTimeout(() => p.fast(false), 20000);
  }

  function restart() {
    Object.assign(load, { cursor: newCursor(), first: true, launchSince: 0, debut: 0 });
    olderBtn.remove();
    conv.replaceChildren();
    skeleton(conv, 4);
    view.showState(null);
    p.now();
  }

  /** L'arbre a changé : un onglet de lancement peut être rebranché, un échec affiché, un état connu. */
  function onTree() {
    if (entry.key.startsWith("launching/")) {
      const node = nodeForTicket(entry.key.slice("launching/".length));
      if (node) { hooks.retarget(node.key, node.title); restart(); }
    } else if (entry.key.startsWith("failed/") && store.loaded) {
      run();
    } else if (!entry.stateInfo) {
      const node = findNode(entry.key);
      if (node) setState(nodeState(node));
    }
  }

  return {
    start() {
      if (entry.key.startsWith("agent/")) skeleton(conv, 4);
      p.start();
    },
    stop() {
      stopped = true;
      p.stop();
      streaming.stop();
      clearTimeout(kickTimer);
    },
    setActive(on) { if (on) p.now(); else streaming.manage(); },
    onShown() { view.hideNewIfAtEnd(); hydrateEventTimes(conv); },
    onTree,
    kick,
    restart,
    get poller() { return p; },
  };
}
