// [desc] Champ de message d'un agent : champ vidé dès l'envoi (rendu si échec), envoi direct (agent qui attend / a fini), mise en FILE si l'agent travaille (jamais d'interruption implicite), reprise d'un agent arrêté, écho immédiat du message, erreurs lisibles. La file d'attente vit dans composer_queue.js. [/desc]

import { api, busy, toast, h } from "../../lib/ui.js";
import { emit, countsChanged } from "../store.js";
import { agentIdOf, composerMode } from "../model.js";
import { createQueue } from "./composer_queue.js";

const KEYS_HINT = "Entrée pour envoyer, Maj+Entrée pour une nouvelle ligne.";

/** Écho immédiat d'un message envoyé, qui devient « envoyé » ou « non envoyé » avec Réessayer. */
function echoMessage(conv, text) {
  const st = h("span", { class: "ag-echo__state" }, "envoi…");
  const el = h("div", { class: "optimistic-echo ag-echo", dataset: { optimistic: "1" } }, h("span", { class: "ag-echo__text" }, text), st);
  conv.appendChild(el);
  return {
    ok(label) { st.textContent = label || "envoyé — l'agent reprend…"; },
    fail(msg, retry) {
      el.classList.remove("optimistic-echo");
      el.classList.add("ag-echo--error");
      const again = h("button", { type: "button", class: "btn btn--sm" }, "Réessayer");
      const drop = h("button", { type: "button", class: "btn btn--ghost btn--sm", "aria-label": "Retirer ce message" }, "×");
      again.addEventListener("click", () => { el.remove(); retry(); });
      drop.addEventListener("click", () => el.remove());
      st.replaceChildren(`non envoyé : ${msg} `, again, drop);
    },
    remove() { el.remove(); },
  };
}

function errorText(err) {
  return err.code === "agent_missing" ? "la fiche de cet agent a disparu ; rien n'a été envoyé." : err.message;
}

const isEnter = (ev) => ev.key === "Enter" && !ev.shiftKey && !ev.isComposing && ev.keyCode !== 229;

export function createComposer(entry, hooks) {
  const input = h("textarea", { class: "textarea ag-composer__input", rows: "2", "aria-label": "Message à l'agent" });
  const send = h("button", { type: "submit", class: "btn btn--primary ag-composer__send" }, "Envoyer");
  const hint = h("div", { class: "ag-composer__hint" });
  const error = h("div", { class: "field__error ag-composer__error", role: "alert" });
  const agentId = () => agentIdOf(entry.key);
  const queue = createQueue(agentId, { deliver: (text) => deliver(text), kick: () => hooks.kick(), conv: () => hooks.conv() });
  const form = h("form", { class: "ag-composer", novalidate: true },
    queue.el, h("div", { class: "ag-composer__row" }, input, send), hint, error);
  let mode = composerMode("");

  function autoGrow() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
  }

  /** POST …/messages ; si l'agent a repris son tour entre deux lectures, on met en file (jamais d'interruption). */
  async function post(text, queued) {
    const url = `/api/agents/${encodeURIComponent(agentId())}/messages`;
    try {
      return await api("POST", url, { text, mode: queued ? "queue" : "refuse" }, { timeout: 60000 });
    } catch (err) {
      const running = err.status === 409 && err.code === "running";
      if (queued || !running) throw err;
      return api("POST", url, { text, mode: "queue" }, { timeout: 60000 });
    }
  }

  function onSent(res, text, echo, blocksAtSend) {
    if (res && res.queued) {
      if (echo) echo.remove();
      queue.addLocal(res.queue_id, text);
      toast.info("L'agent travaille : il lira ton message à sa prochaine étape (après ses outils en cours).");
    } else if (echo) {
      echo.ok();
      queue.trackDirect(text, echo, blocksAtSend);
    }
    hooks.kick();
    emit("refresh-tree");
    countsChanged();
  }

  function setDraft(value) { input.value = value; autoGrow(); }

  /**
   * Envoie `text` à l'agent. `fromInput` : le texte vient du champ, qui est vidé DÈS le départ
   * de l'envoi (comme l'écho qui apparaît au même instant) et le retrouve si l'envoi échoue.
   * Attendre la réponse pour le vider laissait le texte affiché pendant toute la relance de
   * l'agent (respawn : plusieurs secondes, jusqu'à 60 s) : « parti » dans le fil, mais « resté »
   * dans le champ (TODO 2026-09-25 §1).
   * @returns {Promise<boolean>} true si le message est livré ou mis en file.
   */
  async function deliver(text, { fromInput = false } = {}) {
    error.textContent = "";
    const queued = mode.mode === "queue";
    const echo = queued ? null : echoMessage(hooks.conv(), text);
    if (echo) hooks.scrollToEnd();
    if (fromInput) setDraft("");
    //  Repère pris AVANT le POST : une relance à froid peut jouer tout le tour avant l'accusé
    //  (TODO 2026-09-25 §2), et les blocs arrivés entre-temps prouvent que le message est lu.
    const blocksAtSend = queue.mark();
    try {
      const res = await post(text, queued);
      onSent(res, text, echo, blocksAtSend);
      return true;
    } catch (err) {
      // Saisie : le texte REVIENT dans le champ, l'erreur s'affiche dessous. Réponse par bouton
      // d'option : l'écho garde la trace et propose de réessayer.
      if (echo && !fromInput) { echo.fail(errorText(err), () => deliver(text)); return false; }
      if (echo) echo.remove();
      if (fromInput) setDraft(text);
      error.textContent = `Message non envoyé : ${errorText(err)}`;
      return false;
    }
  }

  async function submit() {
    const text = input.value.trim();
    if (!text || mode.mode === "disabled") return;
    await busy(send, mode.mode === "queue" ? "Mise en file…" : "Envoi…", async () => {
      input.readOnly = true;
      try { await deliver(text, { fromInput: true }); } finally { input.readOnly = false; input.focus(); }
    });
  }

  form.addEventListener("submit", (ev) => { ev.preventDefault(); submit(); });
  input.addEventListener("keydown", (ev) => { if (isEnter(ev)) { ev.preventDefault(); submit(); } });
  input.addEventListener("input", () => { autoGrow(); if (error.textContent) error.textContent = ""; });

  return {
    el: form,
    input,
    deliver,
    /** Des messages sortis de la file attendent-ils encore d'apparaître dans le fil ? */
    pending: () => queue.pending(),
    reconcile: (conv, stateKey) => queue.reconcile(conv, stateKey),
    /** Met à jour libellés et comportement d'après l'état de l'agent et la file servie par /blocks
     *  (`polledAt` : instant où cette lecture de /blocks est partie, cf. `queue.sync`). */
    update(stateKey, served, polledAt) {
      mode = composerMode(stateKey);
      input.placeholder = mode.placeholder;
      input.disabled = mode.mode === "disabled";
      send.disabled = mode.mode === "disabled";
      if (!send.getAttribute("aria-busy")) send.textContent = mode.sendLabel;
      //  Aide permanente limitée à ce qui change (livraison différée…) ; les touches passent en infobulle.
      hint.textContent = mode.hint || "";
      hint.hidden = !mode.hint;
      input.title = KEYS_HINT;
      if (Array.isArray(served)) queue.sync(served, polledAt);
    },
  };
}
