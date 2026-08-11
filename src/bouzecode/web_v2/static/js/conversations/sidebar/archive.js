// Archivage (soft-delete réversible) d'une conversation et de tout son sous-arbre,
// derrière un décompte de 3 s annulable : re-cliquer avant la fin n'émet aucun appel.

import { node, agentId } from "../dom.js";
import { NODES } from "../state.js";
import { CONTRACT } from "../contract.js";
import { t } from "../../i18n/index.js";
import { groupRegistry } from "./group.js";
import { refreshList } from "./list.js";

// Archive (soft-delete réversible) une ou plusieurs conversations, puis rafraîchit
// la liste. `keys` est SOIT une clé COMPLÈTE `agent/<id>` (string), SOIT un tableau
// de telles clés (archive-tree : agent + descendants en UN SEUL appel batch — le
// backend /api/conversations/archive accepte déjà body {keys:[...]}).
async function archiveNode(keys) {
  const keyList = Array.isArray(keys) ? keys : [keys];
  if (keyList.length === 0) return;
  // La clé "racine" (celle cliquée) porte le feedback optimiste visuel principal ;
  // on grise aussi les descendants s'ils ont une carte dans la sidebar.
  const recs = keyList.map((k) => groupRegistry.get(k)).filter(Boolean);
  // Feedback OPTIMISTE : on grise/désactive la/les carte(s) IMMÉDIATEMENT, sans
  // attendre la réponse serveur (l'archivage back réclame le worktree = I/O lent).
  for (const rec of recs) {
    if (rec.group) rec.group.classList.add("conv-group--archiving");
  }
  try {
    const resp = await fetch(CONTRACT.archiveUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys: keyList }),
    });
    if (resp.ok) {
      // Succès : refreshList réconcilie et purge la carte (node plus archivé côté serveur).
      await refreshList(true);
      return;
    }
    // Échec HTTP : ROLLBACK visuel, la/les carte(s) redevien(nen)t active(s).
    for (const rec of recs) {
      if (rec.group) rec.group.classList.remove("conv-group--archiving");
    }
  } catch (_) {
    // Réseau : ROLLBACK visuel, on retentera au prochain refresh.
    for (const rec of recs) {
      if (rec.group) rec.group.classList.remove("conv-group--archiving");
    }
  }
}

// Résout l'ARBRE complet à archiver à partir de la clé cliquée : la racine + TOUS
// ses descendants (récursif). Un agent archivé = tout son sous-arbre archivé. La
// relation parent/enfant vit côté agents (NODES issu de /api/agents/tree) : un enfant
// c a `c.parent === id` ou `agentId(c.parent) === id` (hors "dispatcher:*"). BFS.
function collectSubtree(rootKey) {
  const result = [rootKey];
  const seen = new Set([agentId(rootKey)]);
  const queue = [agentId(rootKey)];
  while (queue.length) {
    const parentId = queue.shift();
    for (const c of NODES) {
      const p = c.parent;
      if (!p || p.startsWith("dispatcher:")) continue;
      if (p !== parentId && agentId(p) !== parentId) continue;
      const childId = c.agent_id || agentId(c.key);
      if (!childId || seen.has(childId)) continue;
      seen.add(childId);
      queue.push(childId);
      result.push(c.key || `agent/${childId}`);
    }
  }
  return result;
}

// État de countdown PAR ITEM (jamais un timer global) : Map clé -> { timer }.
// Chaque item a son propre setInterval → countdowns indépendants et non bloquants.
const archiveCountdowns = new Map();

// Le libellé de repos du bouton est TOUJOURS « Archiver » : on le relit dans le
// dictionnaire au lieu de mémoriser le texte affiché, sinon une bascule de langue
// pendant le décompte restaurerait le mot de l'ancienne langue.
function restIdle(btn) {
  btn.textContent = t("sidebar.archive");
  btn.classList.remove("conv-archive-btn--countdown");
}

// Handler du bouton "Archiver" : au lieu d'archiver immédiatement, démarre un décompte
// annulable de 3s ("Annuler 3/2/1"). Re-cliquer pendant le décompte ANNULE (aucun fetch).
// À 0, on résout l'arbre (agent + descendants) et on archive tout en UN appel batch.
export function handleArchiveClick(key, btn) {
  const existing = archiveCountdowns.get(key);
  if (existing) {
    // Clic pendant le décompte = ANNULER : on stoppe le timer, on restaure l'état
    // normal du bouton, AUCUN appel backend n'est émis.
    clearInterval(existing.timer);
    archiveCountdowns.delete(key);
    restIdle(btn);
    return;
  }
  let remaining = 3;
  btn.classList.add("conv-archive-btn--countdown");
  btn.textContent = t("sidebar.cancel_countdown", { seconds: remaining });
  const timer = setInterval(() => {
    remaining -= 1;
    if (remaining > 0) {
      btn.textContent = t("sidebar.cancel_countdown", { seconds: remaining });
      return;
    }
    // Fin du décompte : on nettoie le timer/état AVANT l'archive réelle.
    clearInterval(timer);
    archiveCountdowns.delete(key);
    restIdle(btn);
    archiveNode(collectSubtree(key));
  }, 1000);
  archiveCountdowns.set(key, { timer });
}
