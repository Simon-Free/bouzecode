// [desc] État partagé de la page Agents (derniers nœuds de l'arbre, archivés, clés masquées) et petit bus d'événements entre modules. [/desc]
//
// Les modules ne s'importent pas les uns les autres pour se prévenir : ils émettent ici
// (`emit("refresh-tree")`, `emit("open", …)`) et ceux qui doivent réagir s'abonnent. C'est ce
// qui évite les cycles d'import. `emit` renvoie ce que rendent les abonnés : une action peut
// ainsi attendre un rafraîchissement (`await Promise.all(emit("refresh-tree"))`).

const listeners = new Map();

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event).delete(fn);
}

export function emit(event, payload) {
  const results = [];
  for (const fn of [...(listeners.get(event) || [])]) {
    try { results.push(fn(payload)); } catch (err) {
      // Un abonné défaillant ne doit pas empêcher les autres de réagir : on le signale.
      console.error(`[agents] abonné « ${event} » en erreur`, err);
    }
  }
  return results;
}

/** Émet puis attend tous les abonnés ; un abonné en échec est signalé, pas propagé. */
export async function emitAndWait(event, payload) {
  const settled = await Promise.allSettled(emit(event, payload));
  for (const s of settled) if (s.status === "rejected") console.warn(`[agents] « ${event} »`, s.reason);
}

export const state = {
  /** Derniers nœuds de /api/agents/tree (agents vivants + lancements + échecs). */
  nodes: [],
  /** Nœuds archivés (chargés à la demande quand le groupe « Archivés » est ouvert). */
  archived: [],
  /** Nombre total de racines côté serveur (pagination). */
  totalRoots: 0,
  /** L'arbre a-t-il été chargé au moins une fois ? */
  loaded: false,
  /** Clés masquées le temps d'un archivage (effet immédiat, R3). */
  hiding: new Set(),
};

/** Retrouve un nœud par clé (`agent/<id>`, `launching/<t>`, `failed/<t>`) ou par id nu. */
export function findNode(key) {
  if (!key) return null;
  const all = state.nodes.concat(state.archived);
  return all.find((n) => n.key === key)
    || all.find((n) => n.agent_id && `agent/${n.agent_id}` === key)
    || null;
}

/** Nœud agent né d'un ticket (pour rebrancher un onglet `launching/<ticket>`). */
export function nodeForTicket(ticketId) {
  if (!ticketId) return null;
  return state.nodes.find((n) => n.ticket_id === ticketId && String(n.key).startsWith("agent/"))
    || state.nodes.find((n) => n.ticket_id === ticketId && String(n.key).startsWith("failed/"))
    || null;
}

/** Prévient la navigation (pastilles « À moi » / « en cours ») qu'un compteur a pu changer. */
export function countsChanged() {
  window.dispatchEvent(new CustomEvent("ui:counts-changed"));
}
