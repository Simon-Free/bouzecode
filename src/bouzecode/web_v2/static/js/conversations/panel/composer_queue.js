// [desc] File d'attente des messages à un agent qui travaille : messages en attente (Annuler, « Interrompre et envoyer maintenant »), suivi de leur livraison, et messages jamais lus par l'agent (signalés avec Renvoyer). [/desc]
//
// La file servie par /blocks fait foi : le serveur l'écrit AVANT de répondre 202, ne l'en
// retire qu'une fois le message LU par l'agent, et marque `non_livre` celui qu'un agent
// arrêté ne lira jamais. Un message sorti de la file servie est donc lu, point : on ne le
// déclare plus « pas lu » sur la foi d'un minuteur (TODO 2026-09-25 §2 — l'agent pouvait
// relever le message, répondre et finir son tour entre deux lectures : aucun bloc « après »
// ne venait plus, la bulle rendue en markdown ne reprenait pas le texte brut, et le message
// était annoncé perdu alors qu'il avait bien été pris en compte).
//
// Seul l'envoi DIRECT (agent oisif ou fini, hors file) reste suivi côté client : si l'agent
// s'arrête sans l'avoir lu, on le DIT (R4) au lieu de le perdre.

import { api, busy, toast, h, relTime } from "../../lib/ui.js";

const LOST_AFTER_MS = 15000;
/** Texte comparable à celui d'une bulle rendue : le markdown mange sauts de ligne et espaces. */
const squash = (text) => String(text || "").replace(/\s+/g, "");
const WORKING = new Set(["running", "thinking", "orchestrating", "preparing"]);

/**
 * @param {() => string} agentId
 * @param {{deliver: (text: string) => Promise<boolean>, kick: () => void, conv: () => HTMLElement}} hooks
 */
export function createQueue(agentId, hooks) {
  const el = h("div", { class: "ag-queue", hidden: true, "aria-live": "polite" });
  let serverQueue = [];
  const localQueue = new Map(); // queue_id → item (+ addedAt), en attendant une lecture postérieure à l'accusé
  const inFlight = new Map(); // envois directs : id → {text, since, blocks, echo?}
  const lost = new Map(); // id → {text}
  let lastSig = "";

  const blockCount = () => hooks.conv().querySelectorAll(".block").length;
  const agentUrl = (suffix) => `/api/agents/${encodeURIComponent(agentId())}/${suffix}`;

  async function cancel(it) {
    try {
      await api("DELETE", agentUrl(`queue/${encodeURIComponent(it.id)}`));
      localQueue.delete(it.id);
      serverQueue = serverQueue.filter((s) => s.id !== it.id);
      render();
      toast.ok("Message retiré de la file : il ne sera pas envoyé.");
    } catch (err) {
      if (err.status !== 404) { toast.err(`Impossible de retirer le message : ${err.message}`); return; }
      toast.info("Trop tard : ce message a déjà été livré à l'agent.");
      hooks.kick();
    }
  }

  async function interruptNow() {
    try {
      await api("POST", agentUrl("interrupt"), undefined, { timeout: 30000, okField: true });
      toast.ok("Tour interrompu : l'agent repart avec ton message.");
      hooks.kick();
    } catch (err) {
      toast.err(`Interruption impossible : ${err.message}`);
    }
  }

  /** Oublie un message perdu ; s'il vient du serveur (statut non_livre), il est retiré de la file. */
  async function forget(id, it) {
    if (it.server) {
      try {
        await api("DELETE", agentUrl(`queue/${encodeURIComponent(id)}`));
      } catch (err) {
        if (err.status !== 404) { toast.err(`Impossible de retirer le message : ${err.message}`); return false; }
      }
    }
    lost.delete(id);
    render();
    return true;
  }

  function lostItem(id, it) {
    const again = h("button", { type: "button", class: "btn btn--sm" }, "Renvoyer");
    const drop = h("button", { type: "button", class: "btn btn--ghost btn--sm" }, "Ignorer");
    again.addEventListener("click", () => busy(again, "Envoi…", async () => {
      if (await hooks.deliver(it.text)) await forget(id, it);
    }));
    drop.addEventListener("click", () => busy(drop, "Retrait…", () => forget(id, it)));
    return h("div", { class: "ag-queue__item" },
      h("span", { class: "ag-queue__text" }, `« ${it.text} » n'a pas été lu par l'agent (il s'est arrêté avant).`), again, drop);
  }

  function lostBlock() {
    if (!lost.size) return null;
    return h("div", { class: "error-state error-state--inline ag-queue__lost", role: "alert" },
      ...[...lost].map(([id, it]) => lostItem(id, it)));
  }

  function waitingItem(it) {
    const btn = h("button", { type: "button", class: "btn btn--ghost btn--sm" }, "Annuler");
    btn.addEventListener("click", () => busy(btn, "Retrait…", () => cancel(it)));
    return h("li", { class: "ag-queue__item" },
      h("span", { class: "ag-queue__text" }, it.text), h("span", { class: "ag-queue__when" }, relTime(it.created_at)), btn);
  }

  function waitingHead(count) {
    const now = h("button", { type: "button", class: "btn btn--sm",
      title: "Coupe le tour en cours de l'agent : il repart aussitôt avec les messages en attente." }, "Interrompre et envoyer maintenant");
    now.addEventListener("click", () => busy(now, "Interruption…", interruptNow));
    const s = count > 1 ? "s" : "";
    return h("div", { class: "ag-queue__head" },
      h("span", { class: "spinner spinner--sm", "aria-hidden": "true" }),
      h("span", {}, `${count} message${s} en attente : lu${s} à sa prochaine étape`), now);
  }

  /** Redessine si ce qui est affiché a changé (un bouton recréé à chaque lecture perdrait son clic). */
  function render() {
    const items = serverQueue.concat([...localQueue.values()].filter((it) => !serverQueue.some((s) => s.id === it.id)));
    const sig = JSON.stringify([items.map((it) => [it.id, it.text, relTime(it.created_at)]), [...lost.keys()]]);
    if (sig === lastSig) return;
    lastSig = sig;
    const lostEl = lostBlock();
    el.hidden = !items.length && !lostEl;
    const parts = [lostEl];
    if (items.length) parts.push(waitingHead(items.length), h("ul", { class: "ag-queue__list" }, ...items.map(waitingItem)));
    el.replaceChildren(...parts.filter(Boolean));
  }

  /** Livré = visible dans le fil, OU l'agent a réagi (il travaille, ou des blocs sont arrivés
   *  depuis l'ENVOI — pas depuis l'accusé : le tour a pu se jouer pendant le POST). */
  function delivered(it, seen, busyNow, blocks) {
    return seen.includes(squash(it.text).slice(0, 80)) || busyNow || blocks > it.blocks;
  }

  return {
    el,
    /** Un message vient d'être mis en file (réponse 202 du serveur). */
    addLocal(id, text) {
      localQueue.set(id, { id, text, created_at: new Date().toISOString(), addedAt: Date.now() });
      render();
    },
    /** Repère pris AVANT l'envoi direct, pour `trackDirect`. */
    mark() { return blockCount(); },
    /** Un message envoyé directement : on attend de le voir lu (écho retiré s'il est perdu).
     *  `blocksAtSend` : nombre de blocs au moment de l'ENVOI (`mark()`), pas de l'accusé. */
    trackDirect(text, echo, blocksAtSend = blockCount()) {
      inFlight.set(`direct-${Date.now()}`, { text, since: Date.now(), echo, blocks: blocksAtSend });
    },
    pending() { return inFlight.size > 0; },
    /**
     * File servie par /blocks. `polledAt` : instant où cette lecture est PARTIE ; un message
     * mis en file après (accusé 202 reçu pendant la lecture) ne peut pas y figurer, son
     * absence ne dit donc rien : il reste « en attente » jusqu'à une lecture plus récente.
     */
    sync(queue, polledAt = Infinity) {
      //  `non_livre` : un agent arrêté ne le lira jamais → signalé, avec Renvoyer.
      for (const it of queue.filter((q) => q.statut === "non_livre")) {
        lost.set(it.id, { text: it.text, server: true });
      }
      //  En file ordinaire, ou DÉPOSÉ dans la boîte de l'agent en plein tour (`boite`) : attend
      //  encore d'être lu à sa prochaine étape, reste affiché (et annulable) jusque-là. Poussé à
      //  un process chaud (`en_livraison` sans boîte) : en route, rien à montrer. Absent : LU.
      serverQueue = queue.filter((q) => !q.statut || (q.statut === "en_livraison" && q.boite));
      for (const [id, it] of localQueue) {
        if (queue.some((q) => q.id === id) || it.addedAt <= polledAt) localQueue.delete(id);
      }
      render();
    },
    /** Rapproche les messages en livraison de ce que montre le fil ; signale ceux jamais lus. */
    reconcile(conv, stateKey) {
      if (!inFlight.size && !lost.size) return;
      const seen = [...conv.querySelectorAll(".block.user")].map((b) => squash(b.textContent)).join("\n");
      const blocks = conv.querySelectorAll(".block").length;
      let changed = false;
      for (const [id, it] of lost) {
        if (seen.includes(squash(it.text).slice(0, 80))) { lost.delete(id); changed = true; }
      }
      for (const [id, it] of inFlight) {
        if (delivered(it, seen, WORKING.has(stateKey), blocks)) { inFlight.delete(id); continue; }
        if (Date.now() - it.since <= LOST_AFTER_MS) continue;
        inFlight.delete(id);
        if (it.echo) it.echo.remove();
        lost.set(id, { text: it.text });
        changed = true;
      }
      // Redessiner seulement si la liste a changé : un bouton recréé à chaque lecture perdrait son clic.
      if (changed) render();
    },
  };
}
