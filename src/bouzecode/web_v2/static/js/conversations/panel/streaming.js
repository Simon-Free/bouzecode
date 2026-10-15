// [desc] Streaming token par token d'un agent qui écrit (/partial toutes les 400 ms), seulement quand son onglet est actif et la page visible ; l'affichage provisoire est purgé dès que le streaming s'arrête. [/desc]

import { api } from "../../lib/ui.js";
import { renderStreamingPartial } from "../../shared/session_thread.js";

const PARTIAL_MS = 400;

/**
 * @param {object} entry  onglet (clé, actif, état affiché)
 * @param {HTMLElement} conv  conteneur des messages
 * @param {{pinned: () => boolean, onText: (wasPinned: boolean) => void}} hooks
 *   `onText` est appelé quand du texte ou de la réflexion arrive, avec la position de lecture
 *   d'AVANT l'ajout (pour suivre la génération seulement si l'on était en bas).
 */
export function createStreaming(entry, conv, hooks) {
  let timer = null;
  let stopped = false;

  const wanted = () => !stopped && entry.active && entry.stateInfo && entry.stateInfo.key === "running"
    && entry.key.startsWith("agent/") && document.visibilityState !== "hidden";

  async function tick() {
    timer = null;
    if (stopped) return;
    try {
      const data = await api("GET", `/api/sessions/${entry.key}/partial`, undefined, { timeout: 10000 });
      const wasPinned = hooks.pinned();
      renderStreamingPartial(conv, data || {});
      if (data && (data.text || data.thinking)) hooks.onText(wasPinned);
    } catch (err) {
      // Le fil principal signale déjà les pannes réseau ; on espace simplement le streaming.
      console.warn("streaming interrompu", err.message);
    }
    if (wanted()) timer = setTimeout(tick, PARTIAL_MS);
    else renderStreamingPartial(conv, {});
  }

  /** Démarre ou coupe le streaming selon l'état courant de l'onglet et de l'agent. */
  function manage() {
    if (wanted() && !timer) timer = setTimeout(tick, 0);
    if (!wanted() && timer) { clearTimeout(timer); timer = null; renderStreamingPartial(conv, {}); }
  }

  document.addEventListener("visibilitychange", manage);
  return {
    manage,
    stop() {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", manage);
    },
  };
}
