// Page Conversations : sidebar des managers (racines de /api/agents/tree) +
// onglets internes. Chaque onglet poll /api/sessions/<key>/blocks comme session.js.
// Depuis une conversation, ses subagents (children) s'ouvrent en nouvel onglet.
//
// Ce fichier n'est plus que le POINT D'ENTRÉE : il câble la page et lance le premier
// rendu. Toute la logique vit dans ./conversations/ (voir son README.md).

import { openTabs } from "./conversations/state.js";
import { wireSearch } from "./conversations/search.js";
import { refreshList } from "./conversations/sidebar/list.js";
import { updateComposer } from "./conversations/panel/tabs.js";
import { poll } from "./conversations/panel/poll.js";
import { pollPartial } from "./conversations/panel/streaming.js";
import { sendMsg } from "./conversations/panel/send.js";
import { wireNewConversationBar } from "./conversations/composer/launch.js";
import { loadTypologies, wireAgentBanner } from "./conversations/composer/typology.js";
import { loadProjects, wireProjectBanner } from "./conversations/composer/project.js";
import { wireIsolationBanner } from "./conversations/composer/isolation.js";
import { onLangChange } from "./i18n/index.js";

// Hook de test/debug minimal (aucun effet en prod) : expose le poller et la map
// d'onglets pour piloter la réentrance du poll depuis les tests unitaires (vitest)
// et inspecter l'état live des conversations en console.
if (typeof window !== "undefined") window.__convTest = { poll, pollPartial, openTabs, sendMsg };

// --- Auto-purge des conversations de test (remplace le bouton manuel) --------
// Fire-and-forget au chargement : soft-delete des conversations de test
// (heuristique titre/prompt 'test', non-running) puis rafraîchit la liste.
async function autoPurgeTests() {
  try {
    await fetch("/api/conversations/auto-purge-tests", { method: "POST" });
  } catch (_) {
    // silencieux : l'auto-purge est best-effort, ne bloque jamais l'affichage.
  }
}

// --- Auto-archive des conversations "need input" orphelines (process mort) ---
// Un agent qui a posé une question puis a quitté reste éternellement "à répondre".
// Passé un seuil (12h côté backend), on l'archive (réversible) pour ne pas polluer
// la section "Nécessite une réponse". Les questions récentes restent visibles.
async function autoArchiveStale() {
  try {
    await fetch("/api/conversations/auto-archive-stale", { method: "POST" });
  } catch (_) {
    // silencieux : best-effort, ne bloque jamais l'affichage.
  }
}


// --- Bascule de langue, sans rechargement ------------------------------------
// `applyDom` (dans le noyau i18n) a déjà retraduit tout ce qui porte une clé dans le DOM :
// le chrome du gabarit ET les blocs de conversation rendus par le serveur, qui gardent leurs
// attributs `data-i18n` après insertion. Restent les zones que CE fichier a fait construire
// en JavaScript ; on les redessine par leur chemin normal, celui-là même que le poll emprunte
// chaque seconde et demie — aucun chemin de rendu parallèle à maintenir.
onLangChange(() => {
  refreshList();          // sidebar : pastilles, sections, chips d'activité
  updateComposer();       // onglets et barre de lancement
  loadTypologies();
  loadProjects();
  // Corps des onglets ouverts : `poll` réécrit la ligne meta, la question en attente et le
  // placeholder d'état. Sans blocs neufs à insérer, il ne fait que retraduire.
  openTabs.forEach((_entry, key) => poll(key));
});

wireSearch();
wireNewConversationBar();
updateComposer();
wireAgentBanner();
loadTypologies();
wireProjectBanner();
loadProjects();
wireIsolationBanner();
// Rendu IMMÉDIAT de la sidebar : le 1er paint ne doit PAS attendre les POST de
// maintenance (auto-purge-tests / auto-archive-stale), qui scannent le serveur et
// peuvent prendre des secondes. On affiche d'abord, puis on relance un refresh une
// fois la maintenance terminée (best-effort, en tâche de fond).
refreshList();
Promise.allSettled([autoPurgeTests(), autoArchiveStale()]).finally(refreshList);
setInterval(refreshList, 8000);
