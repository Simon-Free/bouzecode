// Barre « nouvelle conversation » : POST /api/dispatch en `defer`, avec rendu
// OPTIMISTE immédiat d'un node synthétique « starting » qui tient la place tant que
// l'agent réel n'est pas né.

import { node } from "../dom.js";
import { optimisticNodes, setOptimisticNodes } from "../state.js";
import { refreshList } from "../sidebar/list.js";
import { renderList } from "../sidebar/render_list.js";
import { openTab, updateComposer, setComposerForced } from "../panel/tabs.js";
import { chaseLaunch } from "./retarget.js";
import { selectedTypology } from "./typology.js";
import { selectedProject, showProjectSuggestions } from "./project.js";
import { selectedIsolation } from "./isolation.js";

// --- Barre "nouvelle conversation" (façon Claude/ChatGPT) -------------------
// Un champ + une flèche : POST /api/dispatch (comme le Manager de l'accueil),
// puis on ouvre la conversation créée en onglet. Sans champ d'options : le
// dispatcher déduit projet/typologie/modèle du prompt.

export function autoGrowNew(input) {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 200) + "px";
}

// --- Rendu OPTIMISTE d'un nouvel agent -------------------------------------
// Au submit du prompt, /api/dispatch part en defer=true : le serveur répond TÔT
// (ticket_id, sans 'key') et spawn l'agent en fond (plusieurs secondes). Sans
// optimiste, l'agent n'apparaît qu'au refresh où le vrai node existe → délai
// visible. On pousse donc immédiatement un node synthétique "starting" (section
// « En cours ») qui tient la place, puis on le retire dès que le vrai node
// arrive (matching par title_full === prompt) ou si le POST échoue.
// Node synthétique portant TOUS les champs lus par createGroup/updateGroup.
// state:"starting" → isActiveState()===true → section « En cours ».
export function makeOptimisticNode(prompt) {
  const key = `optimistic:${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    key,
    agent_id: "",
    title: prompt.split("\n")[0].slice(0, 90),
    title_full: prompt,
    state: "starting",
    parent: "",
    started_at: new Date().toISOString(),
    archived: false,
    verdict: null,
    suspect_dead: false,
    // Un node optimiste est un agent qu'on vient de DEMANDER : sa vivacité est « running »
    // (jamais crashed), sinon effectiveState l'afficherait « planté » avant même son spawn.
    liveness: "running",
    has_recap: false,
    kind: "",
    branch: "",
    ticket_id: "",
    _optimistic: true,
  };
}

// Retrait propre : on retire simplement le node de la vue (optimisticNodes) puis on
// re-render. Le moteur keyé (reconcileTopLevel) détruit lui-même le row absent de la
// vue via purgeRec + child.remove — NE PAS toucher au DOM/registre à la main ici :
// une suppression manuelle laisse le state du moteur incohérent et fait planter
// reconcileTopLevel (accès à `.children` sur un élément déjà retiré).
export function removeOptimistic(key) {
  const before = optimisticNodes.length;
  setOptimisticNodes(optimisticNodes.filter((o) => o.key !== key));
  if (optimisticNodes.length !== before) renderList();
}

export async function newConversation() {
  const input = document.getElementById("conv-new-input");
  const send = document.getElementById("conv-new-send");
  const err = document.getElementById("conv-new-error");
  const prompt = input.value.trim();
  if (!prompt) return;
  input.disabled = send.disabled = true;
  err.textContent = "";
  // Rendu OPTIMISTE : l'agent apparaît INSTANTANÉMENT (section « En cours »)
  // AVANT l'aller-retour serveur. Réconcilié/retiré plus bas selon l'issue.
  const optNode = makeOptimisticNode(prompt);
  optimisticNodes.push(optNode);
  renderList();
  // Le ticket est TOUJOURS créé côté serveur en defer (persisté avant spawn) :
  // on ne détruit JAMAIS l'optimiste par simple timeout (le spawn — routing +
  // worktree + venv — peut dépasser 20s). Il n'est retiré que sur échec dispatch
  // EXPLICITE (data.error / needs_project / réseau) ou après réconciliation réussie
  // (reconcileOptimistic → retargetTab vers la vraie key). Pas de garde-fou temporel.
  try {
    // "default" (string) plutôt que "" : la typologie retenue est explicite côté serveur
    // (resolve_routing ne devine plus rien).
    // `isolation` : le MÊME vocabulaire à trois valeurs que Agent(isolation=…) côté manager.
    const payload = { prompt, typology: selectedTypology || "default", isolation: selectedIsolation };
    // Projet CHOISI par l'utilisateur. Absent seulement si aucun projet n'est ouvert :
    // l'API répond alors needs_project + suggestions, présentées par showProjectSuggestions.
    if (selectedProject) payload.project_slug = selectedProject;
    // Réactivité "à la volée" : defer=true → le serveur crée le ticket et lance le travail
    // lourd (routing + worktree + spawn, plusieurs secondes) en thread de fond, puis répond
    // TÔT (ticket_id + deferred:true, sans 'key'). Sans ce flag, /api/dispatch part sur le
    // chemin synchrone _launch() et bloque l'input 6-7s avant de répondre.
    payload.defer = true;
    const resp = await fetch("/api/dispatch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json().catch(() => ({}));
    if (data.error) {
      removeOptimistic(optNode.key);
      // On NE vide PAS l'input : le prompt tapé doit rester récupérable.
      input.value = prompt;
      err.textContent = data.error;
      return;
    }
    if (data.needs_project) {
      removeOptimistic(optNode.key);
      input.value = prompt;
      err.textContent = "Choisis un projet ci-dessus avant de lancer la conversation.";
      showProjectSuggestions(data.suggestions);
      return;
    }
    // Identité stable pour la réconciliation : le vrai node (launching/<ticket>
    // puis agent/<id>) porte ce ticket_id. On matche là-dessus plutôt que sur le
    // titre (tardif/générique « agent » au spawn) — cf. reconcileOptimistic.
    optNode.ticket_id = data.ticket_id || "";
    input.value = "";
    autoGrowNew(input);
    setComposerForced(false);
    await refreshList(true);
    if (data.key) openTab(data.key, prompt.split("\n")[0].slice(0, 90));
    updateComposer();
    // Ce refresh-ci est TROP TÔT : en `defer` le serveur vient de répondre et l'agent n'est
    // pas encore spawné. Sans talonnage, sa découverte — puis chacune de ses phases de
    // démarrage — attendait le tick de 8 s.
    if (!data.key) chaseLaunch(optNode.key, optNode.ticket_id);
  } catch (_) {
    removeOptimistic(optNode.key);
    input.value = prompt;
    err.textContent = "réseau : réessaie.";
  } finally {
    input.disabled = send.disabled = false;
    input.focus();
  }
}

export function wireNewConversationBar() {
  const form = document.getElementById("conv-new-bar");
  const input = document.getElementById("conv-new-input");
  if (!form || !input) return;
  form.addEventListener("submit", (e) => { e.preventDefault(); newConversation(); });
  input.addEventListener("input", () => autoGrowNew(input));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); newConversation(); }
  });
}
