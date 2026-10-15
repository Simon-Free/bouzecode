// [desc] Logique PURE de la page Agents : état d'un nœud, arbre parent → enfants, groupes de la liste, filtre, étapes de lancement, mode du champ de message. Aucun DOM, aucun réseau. [/desc]
//
// Tout ce qui décide QUOI afficher vit ici ; les modules de rendu ne font que peindre.
// Vocabulaire : SPEC.md §1 (agent, sous-agent, tâche, dépôt).

import { agentState, AGENT_STATES } from "../lib/states.js";

/** Id d'un nœud à partir de sa clé (`agent/<id>`, `launching/<ticket>`, `failed/<ticket>`). */
export function agentIdOf(key) {
  const k = String(key || "");
  const i = k.indexOf("/");
  return i >= 0 ? k.slice(i + 1) : k;
}

/** Normalise une clé d'agent : accepte `<id>` ou `agent/<id>`. */
export function canonicalKey(key) {
  const k = String(key || "").trim();
  if (!k) return "";
  if (/^(agent|launching|failed)\//.test(k)) return k;
  return `agent/${k}`;
}

const MISSING = { key: "missing", label: "Introuvable", tone: "danger", icon: "!", group: "a_traiter",
  pulse: false, hint: "La fiche de cet agent a disparu : il ne peut plus recevoir de message." };

/** Informations d'état d'un nœud de /api/agents/tree (le serveur sert `etat` : on lui obéit). */
export function nodeState(n) {
  if (!n) return agentState("unknown");
  if (n.etat === "missing") return MISSING;
  if (n.etat && AGENT_STATES[n.etat]) {
    const st = agentState(n.etat);
    // Le serveur précise parfois le libellé (ex. « Terminé — intégré » : tué après avoir intégré).
    return n.integre && n.libelle_etat ? { ...st, label: n.libelle_etat } : st;
  }
  return agentState(n);
}

/** L'agent attend-il un geste de l'utilisateur (question, plan à valider) ? */
export function isAwaitingUser(st) {
  return st.key === "awaiting_input" || st.key === "awaiting_plan_validation";
}

const ATTENTION = new Set(["awaiting_input", "awaiting_plan_validation", "crashed", "launch_failed", "missing"]);

/** Un parent est-il « réel » (un autre agent) plutôt qu'une étiquette `dispatcher:*` ? */
function realParent(n) {
  const p = String(n.parent || "");
  if (!p || p.startsWith("dispatcher:")) return "";
  return agentIdOf(p);
}

function idOf(n) { return n.agent_id || agentIdOf(n.key); }

/**
 * Construit l'arbre : index par id d'agent, enfants par parent, racines (nœuds sans parent
 * présent dans la liste). Un sous-agent dont le parent a disparu devient une racine (jamais
 * perdu).
 * @returns {{byId: Map<string, object>, children: Map<string, object[]>, roots: object[]}}
 */
export function buildTree(nodes) {
  const list = nodes || [];
  const byId = new Map();
  for (const n of list) if (idOf(n) && !byId.has(idOf(n))) byId.set(idOf(n), n);
  const children = new Map();
  const roots = [];
  for (const n of list) {
    const pid = realParent(n);
    const hasParent = pid && byId.has(pid) && byId.get(pid) !== n;
    if (!hasParent) { roots.push(n); continue; }
    if (!children.has(pid)) children.set(pid, []);
    children.get(pid).push(n);
  }
  return { byId, children, roots };
}

/** Tous les descendants d'un id (profondeur illimitée, sans boucle). */
export function descendantsOf(tree, id) {
  const out = [];
  const seen = new Set([id]);
  const queue = [id];
  while (queue.length) {
    for (const c of tree.children.get(queue.shift()) || []) {
      if (seen.has(idOf(c))) continue;
      seen.add(idOf(c));
      out.push(c);
      queue.push(idOf(c));
    }
  }
  return out;
}

function plural(n, one, many) { return n > 1 ? many : one; }

/** Libellé agrégé des sous-agents : « 3 sous-agents · 1 attend ta réponse · 1 arrêté · 1 en cours ». */
export function childrenSummary(kids) {
  if (!kids.length) return "";
  const states = kids.map(nodeState);
  const waiting = states.filter(isAwaitingUser).length;
  const failed = states.filter((s) => s.group === "a_traiter" && !isAwaitingUser(s)).length;
  const running = states.filter((s) => s.group === "en_cours").length;
  return [
    `${kids.length} ${plural(kids.length, "sous-agent", "sous-agents")}`,
    waiting ? `${waiting} ${plural(waiting, "attend", "attendent")} ta réponse` : "",
    failed ? `${failed} ${plural(failed, "arrêté", "arrêtés")}` : "",
    running ? `${running} en cours` : "",
  ].filter(Boolean).join(" · ");
}

/** Le nœud correspond-il au filtre texte (titre, prompt, tâche, dépôt, id, branche) ? */
export function matchesFilter(n, q) {
  const query = String(q || "").trim().toLowerCase();
  if (!query) return true;
  const hay = [n.title, n.title_full, n.tache_titre, n.project_name, n.project_slug, n.agent_id, n.branch]
    .filter(Boolean).join(" \u0001 ").toLowerCase();
  return query.split(/\s+/).every((w) => hay.includes(w));
}

function recency(n) {
  return String(n.saved_at || n.last_activity || n.started_at || "");
}

/** Groupe d'une racine : ce qui attend l'utilisateur, ce qui travaille (lui ou un descendant), le reste. */
function rootGroup(root, desc) {
  const st = nodeState(root);
  if (ATTENTION.has(st.key)) return "a_traiter";
  if (st.group === "en_cours" || desc.some((d) => nodeState(d).group === "en_cours")) return "en_cours";
  return "termines";
}

/** Sous-agents qui attendent l'utilisateur : remontés en propre dans « À traiter ». */
function flatSubagentsNeedingUser(nodes, tree, q) {
  const titleOf = (n) => n.title || n.tache_titre || n.agent_id || n.key;
  return (nodes || [])
    .filter((n) => realParent(n) && tree.byId.has(realParent(n)))
    .filter((n) => ATTENTION.has(nodeState(n).key) && matchesFilter(n, q))
    .map((n) => ({ node: n, kids: [], parentTitle: titleOf(tree.byId.get(realParent(n))), flatKey: `${n.key}::flat` }));
}

/** « À traiter » : les questions d'abord (le geste le plus rapide), puis les plus anciennes. */
function byUrgency(a, b) {
  const qa = isAwaitingUser(nodeState(a.node)) ? 0 : 1;
  const qb = isAwaitingUser(nodeState(b.node)) ? 0 : 1;
  return qa - qb || recency(a.node).localeCompare(recency(b.node));
}

const byRecency = (a, b) => recency(b.node).localeCompare(recency(a.node));

/**
 * Range les nœuds en groupes pour la liste (SPEC §5.2).
 *  - « À traiter » : tout agent (racine OU sous-agent) qui attend l'utilisateur — un
 *    sous-agent y apparaît en propre, avec le titre de son agent principal (`parentTitle`).
 *  - « En cours » / « Terminés » : les racines, selon leur état ; un agent principal dont un
 *    sous-agent travaille est « en cours ».
 * Chaque entrée : {node, kids, parentTitle?, flatKey}. `flatKey` est unique dans la liste
 * (un sous-agent peut figurer à la fois dans « À traiter » et sous son parent).
 * @param {object[]} nodes
 * @param {{filter?: string}} [opts]
 */
export function groupNodes(nodes, opts = {}) {
  const tree = buildTree(nodes);
  const q = opts.filter || "";
  const groups = { a_traiter: [], en_cours: [], termines: [] };
  for (const root of tree.roots) {
    const desc = descendantsOf(tree, idOf(root));
    if (!matchesFilter(root, q) && !desc.some((d) => matchesFilter(d, q))) continue;
    groups[rootGroup(root, desc)].push({ node: root, kids: tree.children.get(idOf(root)) || [], flatKey: root.key });
  }
  groups.a_traiter.push(...flatSubagentsNeedingUser(nodes, tree, q));
  groups.a_traiter.sort(byUrgency);
  groups.en_cours.sort(byRecency);
  groups.termines.sort(byRecency);
  return { groups, tree };
}

// ---------------------------------------------------------------- lancement

/** Étapes affichées pendant le lancement d'un agent (SPEC §5.4). */
export const LAUNCH_STEPS = [
  { key: "sent", label: "Demande envoyée" },
  { key: "env", label: "Préparation de l'environnement" },
  { key: "boot", label: "Démarrage de l'agent" },
  { key: "model", label: "Le modèle lit ta demande" },
];

/**
 * Index de l'étape courante (0..3) d'après un statut servi par /blocks.
 * @param {{state?:string, phase?:string, phase_label?:string}} status
 * @param {boolean} launching  la clé est encore `launching/<ticket>` (aucun agent né)
 */
export function launchStepIndex(status, launching) {
  const s = status || {};
  if (launching) return /démarrage|spawn/i.test(String(s.phase_label || s.phase || "")) ? 2 : 1;
  if (s.phase === "attente_modele") return 3;
  const booting = s.phase === "demarrage" || s.state === "starting" || s.state === "provisioning";
  return booting ? 2 : 3;
}

// ---------------------------------------------------------------- champ de message

const QUEUE_WHILE_WORKING = { mode: "queue", sendLabel: "Mettre en file",
  placeholder: "L'agent travaille : il lira ton message à sa prochaine étape…",
  hint: "Rien n'est interrompu : il le lira à sa prochaine étape, après ses outils en cours." };
const DIRECT_AFTER_END = { mode: "direct", sendLabel: "Envoyer",
  placeholder: "Écris pour continuer la conversation avec cet agent…",
  hint: "L'agent reprendra la conversation avec ce message." };
const ANSWER = { mode: "direct", sendLabel: "Répondre", placeholder: "Réponds à l'agent…", hint: "" };
const disabled = (placeholder) => ({ mode: "disabled", sendLabel: "Envoyer", placeholder, hint: "" });

const COMPOSER_MODES = {
  running: QUEUE_WHILE_WORKING,
  thinking: QUEUE_WHILE_WORKING,
  orchestrating: QUEUE_WHILE_WORKING,
  preparing: { mode: "queue", sendLabel: "Mettre en file",
    placeholder: "L'agent démarre : ton message lui sera livré dès qu'il aura fini son premier tour…", hint: "" },
  awaiting_input: ANSWER,
  awaiting_plan_validation: ANSWER,
  idle: DIRECT_AFTER_END,
  finished: DIRECT_AFTER_END,
  crashed: { mode: "resume", sendLabel: "Continuer avec ce message",
    placeholder: "Continuer avec ce message… (l'agent reprend là où il s'est arrêté)",
    hint: "L'agent redémarre dans la même conversation avec ton message." },
  launch_failed: disabled("Le lancement a échoué : réessaie-le ci-dessus."),
  missing: disabled("Cet agent n'existe plus : impossible de lui écrire."),
  archived: disabled("Agent archivé : restaure-le pour lui écrire."),
};
const DEFAULT_MODE = { mode: "direct", sendLabel: "Envoyer", placeholder: "Écris à l'agent…", hint: "" };

/**
 * Comportement du champ de message selon l'état de l'agent (SPEC §5.3).
 * @returns {{mode: "direct"|"queue"|"resume"|"disabled", placeholder: string, hint: string, sendLabel: string}}
 */
export function composerMode(stateKey) {
  return COMPOSER_MODES[stateKey] || DEFAULT_MODE;
}

/** Libellés de l'environnement d'exécution (SPEC §5.4). */
export const ISOLATIONS = [
  { value: "shared", label: "Dépôt principal",
    hint: "L'agent travaille directement dans le dépôt. Le plus rapide ; pour une tâche courte ou un seul agent qui écrit." },
  { value: "worktree", label: "Copie isolée",
    hint: "Une copie git dédiée (worktree). Dès que plusieurs agents écrivent en parallèle sur le même dépôt." },
  { value: "worktree_venv", label: "Copie isolée + dépendances",
    hint: "Copie git ET environnement Python dédiés. Seulement si l'agent touche aux dépendances (~30 s de plus)." },
];

/** Environnement par défaut d'un lancement humain (décision D3) : une copie isolée. */
export const DEFAULT_ISOLATION = "worktree";

/** Valeur d'isolation connue du serveur ; l'ancienne forme `worktree+venv` est ramenée à la nouvelle. */
export function normalizeIsolation(value) {
  const v = value === "worktree+venv" ? "worktree_venv" : value;
  return ISOLATIONS.some((i) => i.value === v) ? v : DEFAULT_ISOLATION;
}

export function isolationLabel(value) {
  const v = value === "worktree+venv" ? "worktree_venv" : value;
  const it = ISOLATIONS.find((i) => i.value === v);
  return it ? it.label : "Dépôt principal";
}

/** Corps de `POST /api/projects/<slug>/tickets` pour un lancement depuis l'écran : le titre
 *  (obligatoire côté serveur) est la première ligne du prompt ; lancement en fond. */
export function ticketBody(launch) {
  return {
    title: titleFromPrompt(launch.prompt, 200) || "Agent",
    prompt: launch.prompt,
    typology: launch.typology || "default",
    isolation: normalizeIsolation(launch.isolation),
    launch: true,
    defer: true,
  };
}

/** Première ligne d'un prompt, tronquée : titre d'onglet provisoire. */
export function titleFromPrompt(prompt, max = 80) {
  const first = String(prompt || "").split("\n").find((l) => l.trim()) || "";
  const t = first.trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}
