// [desc] Encarts d'état du fil d'un agent (au-dessus des messages) : étapes du lancement, lancement échoué, agent introuvable, conversation vide, erreur de chargement. Constructeurs DOM sans état. [/desc]

import { h } from "../../lib/ui.js";
import { LAUNCH_STEPS } from "../model.js";

const STALL_TEXT = "C'est plus long que d'habitude. Si rien ne bouge, regarde la liste à gauche : un lancement échoué y apparaît dans « À traiter ».";

function stepIcon(done, current) {
  if (done) return "✓";
  return current ? h("span", { class: "spinner spinner--sm" }) : "○";
}

function stepItem(step, i, index, detail) {
  const done = i < index;
  const current = i === index;
  const status = done ? " (fait)" : (current ? " (en cours)" : " (à venir)");
  return h("li", { class: `ag-steps__item${done ? " is-done" : ""}${current ? " is-current" : ""}` },
    h("span", { class: "ag-steps__icon", "aria-hidden": "true" }, stepIcon(done, current)),
    h("span", {}, step.label, current && detail ? h("span", { class: "ag-steps__detail" }, ` — ${detail}`) : null),
    h("span", { class: "sr-only" }, status));
}

/** Progression du lancement ; `stalled` ajoute un avertissement quand c'est anormalement long. */
export function launchSteps(index, detail, stalled) {
  return h("div", { class: "ag-launching", role: "status" },
    h("div", { class: "ag-launching__title" }, "Lancement de l'agent"),
    h("ol", { class: "ag-steps", "aria-label": "Progression du lancement" }, ...LAUNCH_STEPS.map((s, i) => stepItem(s, i, index, detail))),
    stalled ? h("p", { class: "ag-launching__warn" }, STALL_TEXT) : null);
}

export function launchFailure(reason) {
  return h("div", { class: "error-state", role: "alert" },
    h("div", { class: "error-state__title" }, "Lancement échoué"),
    h("div", { class: "error-state__text" }, reason || "L'agent n'a pas pu démarrer."),
    h("div", { class: "error-state__text" }, "Utilise « Réessayer le lancement » en haut de ce panneau : ta demande est conservée."));
}

/** Agent introuvable : Restaurer (s'il a été archivé) et Fermer l'onglet. */
export function notFound(err, onRestore, onClose) {
  const restore = h("button", { type: "button", class: "btn btn--primary btn--sm" }, "Restaurer");
  restore.addEventListener("click", async () => { restore.disabled = true; await onRestore(); });
  const close = h("button", { type: "button", class: "btn btn--sm" }, "Fermer l'onglet");
  close.addEventListener("click", onClose);
  return h("div", { class: "empty" },
    h("div", { class: "empty__title" }, "Cet agent n'existe plus (archivé ou supprimé)."),
    h("div", { class: "empty__text" }, err && err.message ? err.message : "S'il a été archivé, tu peux le restaurer."),
    h("div", { class: "btn-row" }, restore, close));
}

export function emptyConversation() {
  return h("p", { class: "ag-muted" }, "Aucun message dans cette conversation.");
}

export function loadError(err) {
  return h("div", { class: "error-state", role: "alert" },
    h("div", { class: "error-state__title" }, "Impossible de charger la conversation."),
    h("div", { class: "error-state__text" }, `${err.message} Nouvel essai automatique…`));
}

/** Rattache chaque résultat d'outil à son appel (le serveur les rend séparément). */
export function pairToolBlocks(conv) {
  conv.querySelectorAll("details.tr[data-tool-call-id]").forEach((tr) => {
    if (tr.dataset.paired) return;
    const tc = conv.querySelector(`details.tc[data-tool-id="${CSS.escape(tr.dataset.toolCallId)}"]`);
    if (tc) { tc.appendChild(tr); tr.dataset.paired = "1"; }
  });
}
