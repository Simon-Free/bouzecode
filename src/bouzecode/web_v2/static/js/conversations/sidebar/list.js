// Chargement de la sidebar : pagination des racines, garde anti-render pendant une
// interaction, et rafraîchissement périodique (8 s) de /api/agents/tree.

import { NODES, setNodes } from "../state.js";
import { remapLaunchingTabs, reconcileOptimistic } from "../composer/retarget.js";
import { renderList } from "./render_list.js";

// --- Pagination A' (lazy-scroll des racines) ---------------------------------
// /api/agents/tree?offset&limit sert `limit` RACINES (managers) triées à partir
// d'`offset`, chaque racine embarquant ses sous-agents (git calculé SEULEMENT sur
// les nodes servis → plus de fetch 27s/NetworkError). On charge PAGE_LIMIT racines
// à la fois ; l'IntersectionObserver déclenche la page suivante au scroll.
const PAGE_LIMIT = 12;
export let seqLoaded = 0;            // nb de racines SÉQUENTIELLES chargées (= offset pur, ignore les forcées page0)
export let totalRoots = 0;          // total de racines côté serveur (réponse.total_roots)
let loadingMore = false;      // garde anti-double-fetch pendant un loadNextPage
let scrollObserver = null;    // IntersectionObserver sur la sentinelle de bas de liste

// Garde anti-render pendant une interaction (clic/hover en cours).
let interacting = false;
let pendingRefresh = false;
let guardInstalled = false;

export function installInteractionGuard() {
  if (guardInstalled) return;
  guardInstalled = true;
  const list = document.getElementById("conv-list");
  if (list) {
    list.addEventListener("pointerdown", () => { interacting = true; });
  }
  document.addEventListener("pointerup", () => {
    interacting = false;
    if (pendingRefresh) { pendingRefresh = false; refreshList(true); }
  });
}

export async function refreshList(force = false) {
  // Garde : un refresh AUTO (setInterval) pendant une interaction est différé et
  // rejoué au pointerup. Les mutations manuelles passent force=true (hors garde).
  if (!force && interacting) { pendingRefresh = true; return; }
  // Résilience réseau : un fetch qui THROW (NetworkError — serveur en reload,
  // connexion coupée, payload interrompu) ne doit PAS casser la chaîne ni laisser
  // "Uncaught (in promise)". On retourne silencieusement : le setInterval(8s)
  // rejouera et la sidebar se débloque dès que le serveur répond à nouveau.
  // Refresh COMPLET (poller 8s / mutations) : on refetch en UNE requête tout le
  // séquentiel déjà chargé (offset=0, limit=max(seqLoaded, PAGE_LIMIT)) → le scroll
  // n'est pas perdu (rendu keyé reconcile) et le forçage page0 (racines vivantes)
  // reste appliqué. Résilience réseau : un fetch qui THROW (NetworkError — serveur
  // en reload, connexion coupée) ne casse pas la chaîne ; le setInterval(8s) rejoue.
  const limit = Math.max(seqLoaded, PAGE_LIMIT);
  let nodes, tot;
  try {
    const resp = await fetch(`/api/agents/tree?offset=0&limit=${limit}`);
    if (!resp.ok) return;
    ({ nodes, total_roots: tot } = await resp.json());
  } catch (e) {
    console.warn("refreshList: fetch /api/agents/tree failed (retry next tick)", e);
    return;
  }
  setNodes(nodes || []);
  remapLaunchingTabs();
  totalRoots = tot || 0;
  seqLoaded = Math.min(limit, totalRoots);
  // Retire les optimistes dont le vrai node est arrivé (avant le concat du render).
  reconcileOptimistic();
  renderList();
}

// Installe/positionne la sentinelle + IntersectionObserver déclenchant loadNextPage().
export function ensureScrollSentinel(list) {
  if (!list) return;
  let sentinel = list.querySelector(":scope > .conv-load-sentinel");
  if (seqLoaded >= totalRoots) {
    // Tout est chargé : retirer la sentinelle si présente.
    if (sentinel) sentinel.remove();
    return;
  }
  if (!sentinel) {
    sentinel = document.createElement("div");
    sentinel.className = "conv-load-sentinel";
    sentinel.setAttribute("aria-hidden", "true");
  }
  // Toujours la remettre en DERNIER enfant (les groups ont pu être déplacés/insérés).
  list.appendChild(sentinel);
  if (!scrollObserver) {
    scrollObserver = new IntersectionObserver((entries) => {
      if (entries.some((en) => en.isIntersecting)) loadNextPage();
    }, { root: null, rootMargin: "200px" });
  } else {
    scrollObserver.disconnect();
  }
  scrollObserver.observe(sentinel);
}

// Charge la page suivante de racines (offset=seqLoaded), APPEND aux NODES (dédup par
// key) puis re-render. Garde loadingMore : une seule requête en vol. Résilience réseau
// identique à refreshList (un throw ne casse pas la chaîne).
export async function loadNextPage() {
  if (loadingMore || seqLoaded >= totalRoots) return;
  loadingMore = true;
  try {
    const resp = await fetch(`/api/agents/tree?offset=${seqLoaded}&limit=${PAGE_LIMIT}`);
    if (!resp.ok) return;
    const { nodes, total_roots: tot } = await resp.json();
    totalRoots = tot || totalRoots;
    const known = new Set(NODES.map((n) => n.key));
    for (const n of nodes || []) {
      if (!known.has(n.key)) { NODES.push(n); known.add(n.key); }
    }
    seqLoaded = Math.min(seqLoaded + PAGE_LIMIT, totalRoots);
    renderList();
  } catch (e) {
    console.warn("loadNextPage: fetch /api/agents/tree failed (retry on next scroll)", e);
  } finally {
    loadingMore = false;
  }
}
