// Groupement et rendu de #conv-list à partir de NODES : racines, entrées fantômes
// (parent archivé), sectionnement par état. Séparé du chargement pour être rejoué
// après un loadNextPage sans refetch.

import { node, agentId } from "../dom.js";
import { NODES, setNodes, optimisticNodes } from "../state.js";
import { CONTRACT } from "../contract.js";
import { isActiveState } from "../badges.js";
import { emptyMsgEl, setEmptyMsgEl } from "./group.js";
import { reconcileTopLevel } from "./reconcile.js";
import { installInteractionGuard, ensureScrollSentinel } from "./list.js";

// Rattache les sous-agents internes hérités dont le parent est un littéral
// "dispatcher:*" (hors "dispatcher:manual") qu'AUCUN node ne porte comme id : réécrit
// leur parent vers le codeur partageant la même branche/worktree, pour qu'ils
// s'imbriquent sous lui au lieu de disparaître (garde-fou roots ligne ~100).
function resolveOrphanParents() {
  const isResolvable = (parent) =>
    NODES.some((p) =>
      p.agent_id === parent || p.key === parent ||
      agentId(p.key) === agentId(parent)
    );
  NODES.forEach((n) => {
    if (!n.parent || !n.parent.startsWith("dispatcher:")) return;
    if (n.parent === "dispatcher:manual") return;
    if (isResolvable(n.parent)) return; // migration boot a déjà rattaché → rien à faire
    // Candidat = codeur du MÊME worktree/branche : même branch non vide, autre node,
    // dont le parent n'est PAS lui-même un orphelin dispatcher:* (on veut le codeur).
    const candidate = NODES.find((c) =>
      c.key !== n.key &&
      c.branch && c.branch === n.branch &&
      !(c.parent && c.parent.startsWith("dispatcher:") && c.parent !== "dispatcher:manual")
    );
    if (candidate) n.parent = agentId(candidate.key);
  });
}

// renderList() : groupement + rendu de #conv-list à partir de NODES (déjà fusionné,
// toutes pages confondues). Séparé de refreshList pour être rejoué après un
// loadNextPage (append) sans refetch. Toute la logique de groupement (parent/enfant,
// ghosts, sections) opère sur NODES et est INDÉPENDANTE de la pagination.
export function renderList() {
  const nodes = NODES;
  // Fallback (sessions héritées) : un sous-agent interne créé avant le fix 4c8c410 porte
  // un parent littéral "dispatcher:validate"/"dispatcher:auto-merge" que la migration boot
  // n'a pas pu résoudre (ticket disparu). Plutôt que de le faire DISPARAÎTRE (le garde-fou
  // roots l'exclut des racines), on le rattache au codeur partageant sa branche/worktree.
  resolveOrphanParents();
  const list = document.getElementById("conv-list");
  installInteractionGuard();
  // Base = uniquement les vrais nodes. On PURGE tout optimiste résiduel laissé dans
  // NODES par un render précédent (NODES est persistant/réassigné) : la source de
  // vérité des optimistes est la liste `optimisticNodes`, pas NODES. Sans cette
  // purge, un optimiste retiré de `optimisticNodes` (removeOptimistic → renderList
  // hors refreshList) resterait STALE dans NODES et ne disparaîtrait jamais.
  setNodes(nodes.filter((n) => !n._optimistic));
  // Fusion des optimistes vivants (entrées "starting" tenant la place avant que
  // le vrai node du tree n'existe). Retirés par reconcileOptimistic() dès arrivée.
  if (optimisticNodes.length) setNodes(NODES.concat(optimisticNodes));

  // Le parent (agent_id ou key) d'un node est-il présent dans l'arbre ?
  const parentPresent = (parent) => {
    const pid = agentId(parent);
    return NODES.some((p) =>
      p.parent !== undefined &&
      (p.key === parent || p.agent_id === parent ||
       agentId(p.key) === parent || p.agent_id === pid || agentId(p.key) === pid)
    );
  };
  // Un node est-il un ORPHELIN de validation ? kind ∈ {validate, merge} avec un
  // parent réel (agent codeur) désormais ABSENT de l'arbre (conversation archivée,
  // purgée, session disparue). La spec (§2) impose qu'un tel node ne soit JAMAIS
  // une racine standard : il doit rester rattaché sous une entrée fantôme.
  const isValidationOrphan = (n) => {
    if (n._ghost) return false;
    if (!(n.kind === "validate" || n.kind === "merge")) return false;
    if (!n.parent || n.parent.startsWith("dispatcher:")) return false;
    return !parentPresent(n.parent);
  };

  // Racines : voir logique d'exclusion (archivées + subagents imbriqués + orphelins validate/merge).
  const roots = NODES.filter((n) => {
    if (CONTRACT.isArchived(n)) return false;
    // §2 : un validateur/merger orphelin n'est jamais une racine (même parent absent).
    if (isValidationOrphan(n)) return false;
    if (!n.parent) return true;
    if (n.parent.startsWith("dispatcher:") && n.parent !== "dispatcher:manual") return false;
    return !parentPresent(n.parent);
  });

  // §3 — APPROCHE FANTÔME FRONT (choisie, cf. methodology) : le backend ne peut PAS
  // ré-injecter un parent disparu (agent_tree ne liste que les agents vivants), donc
  // c'est le front qui fabrique une entrée fantôme repliée et grisée par parent absent.
  // Chaque orphelin validate/merge s'imbrique dessous via childrenOf (match agent_id).
  const orphanParentIds = new Set();
  NODES.forEach((n) => { if (isValidationOrphan(n)) orphanParentIds.add(agentId(n.parent)); });
  const ghosts = [...orphanParentIds].map((pid) => ({
    key: `ghost/${pid}`,
    agent_id: pid,
    parent: "",
    state: "finished",
    _ghost: true,
    title: `⌀ conversation archivée · #${String(pid).slice(0, 8)}`,
    title_full: "Conversation parente archivée, purgée ou disparue — validateur rattaché ci-dessous.",
  }));

  // Cas vide : message unique, on purge tout le reste. NB : s'il existe des
  // entrées fantômes (orphelins validate/merge dont le parent a disparu), on
  // NE tombe PAS dans le cas vide — le flux normal les rend en « Terminés ».
  if (!roots.length && !ghosts.length) {
    reconcileTopLevel(list, [], []);
    if (!emptyMsgEl) setEmptyMsgEl(node(list, "p", "muted", "Aucune conversation manager."));
    else if (emptyMsgEl.parentNode !== list) list.appendChild(emptyMsgEl);
    return;
  }
  if (emptyMsgEl) { emptyMsgEl.remove(); setEmptyMsgEl(null); }

  // Sectionnement par ÉTAT (ordre fixe a→b→c) :
  //   a) ⚠ Nécessite une réponse : awaiting_* (CONTRACT.needsInput)
  //   b) ● En cours : running (hors needsInput)
  //   c) Terminés : finished | cli | autre (hors needsInput/running)
  // Sous-agents IMBRIQUÉS = nodes non archivés qui ne sont PAS des racines et ont un parent.
  const rootKeys = new Set(roots.map((r) => r.key));
  const subagents = NODES.filter(
    (n) => !CONTRACT.isArchived(n) && n.parent && !rootKeys.has(n.key)
  );
  // Titre du parent d'un sous-agent (pour le lien « ↳ sous-agent de {titre} »).
  const parentTitleOf = (sub) => {
    const pid = agentId(sub.parent);
    const p = NODES.find((c) =>
      c.key === sub.parent || c.agent_id === sub.parent ||
      agentId(c.key) === sub.parent || c.agent_id === pid || agentId(c.key) === pid
    );
    return p ? (p.title || p.agent_id || p.key) : sub.parent;
  };
  // Clone une entrée FLAT (key dérivée ::flat → 2 recs DOM distincts sans collision).
  const flat = (sub) => ({ ...sub, key: `${sub.key}::flat`, _realKey: sub.key, _flatOf: parentTitleOf(sub) });

  // a) needsInput : racines needsInput + sous-agents needsInput (en propre, flat).
  const needInput = [
    ...roots.filter((n) => CONTRACT.needsInput(n)),
    ...subagents.filter((n) => CONTRACT.needsInput(n)).map(flat),
  ];
  // b) running : racines ACTIVES (running OU manager en attente d'enfants, hors needsInput)
  //    UNIQUEMENT. Les sous-agents running NE remontent PAS à la racine : ils restent
  //    accessibles via le toggle "N sous-agents · X en cours" de leur racine parent.
  const running = [
    ...roots.filter((n) => isActiveState(n) && !CONTRACT.needsInput(n)),
  ];
  // c) Terminés : racines restantes UNIQUEMENT (sous-agents terminés restent imbriqués,
  //    zéro doublon de premier niveau). Un manager en attente n'y tombe PAS (il est actif).
  const finished = roots.filter(
    (n) => !CONTRACT.needsInput(n) && !isActiveState(n)
  );
  // §3/§4 : les entrées fantômes (parents archivés) vont en « Terminés », repliées par
  // défaut, grisées. Leurs orphelins restent visibles et ouvrables dessous (childrenOf).
  finished.push(...ghosts);

  reconcileTopLevel(list, needInput, running, finished);

  // Sentinelle de lazy-scroll : réappendue en dernier enfant de #conv-list tant qu'il
  // reste des racines à charger (seqLoaded < totalRoots). Ce n'est PAS un .conv-group
  // ni une section → reconcileTopLevel ne la retire jamais (survit à chaque render).
  ensureScrollSentinel(list);
}
