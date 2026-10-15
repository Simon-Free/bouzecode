// [desc] Lexique UNIQUE des états d'agent et des statuts de tâche (SPEC §1.1-§1.2) : libellé, ton, icône, groupe. [/desc]
//
// Toute page qui affiche un état passe par ici : c'est ce qui garantit qu'un agent ne peut
// pas être « terminé » sur le Bureau et « planté » dans la liste des agents. Les MOTS viennent
// du lexique unique du serveur (services/work/lexique.py), injecté par base.html dans
// <script id="bz-lexique"> : les valeurs écrites ici n'en sont que la copie par défaut (tests,
// page servie sans lexique), tenue égale par tests/test_lexique_unique.py. Les mots techniques
// du backend (running, idle, cli…) ne sortent jamais tels quels.
//
// Tons (→ couleurs de ds.css) : info (vivant), warn (attend l'utilisateur), danger (échec),
// ok (terminé), neutral (inactif / archivé). Un état n'est JAMAIS porté par la seule
// couleur : chaque entrée a une icône de forme distincte et un libellé.

/** @typedef {{key:string, label:string, tone:string, icon:string, group:string, pulse:boolean, hint:string}} StateInfo */

// ---------------------------------------------------------------- agents

/** Groupes de la liste des agents (ordre d'affichage). */
export const AGENT_GROUPS = [
  { key: "a_traiter", label: "À traiter" },
  { key: "en_cours", label: "En cours" },
  { key: "termines", label: "Terminés" },
  { key: "archives", label: "Archivés" },
];

/** @type {Record<string, Omit<StateInfo,"key">>} */
export const AGENT_STATES = {
  preparing: { label: "Préparation…", tone: "info", icon: "◌", group: "en_cours", pulse: true,
    hint: "L'environnement de l'agent se prépare (copie du dépôt, dépendances, démarrage)." },
  thinking: { label: "Le modèle lit ta demande…", tone: "info", icon: "◌", group: "en_cours", pulse: true,
    hint: "La première réponse est la plus lente : le modèle met ton contexte en mémoire." },
  running: { label: "En cours", tone: "info", icon: "●", group: "en_cours", pulse: true,
    hint: "L'agent travaille." },
  orchestrating: { label: "Attend ses sous-agents", tone: "info", icon: "●", group: "en_cours", pulse: true,
    hint: "L'agent a lancé des sous-agents et attend qu'ils finissent." },
  awaiting_input: { label: "Attend ta réponse", tone: "warn", icon: "?", group: "a_traiter", pulse: false,
    hint: "L'agent t'a posé une question." },
  awaiting_plan_validation: { label: "Plan à valider", tone: "warn", icon: "?", group: "a_traiter", pulse: false,
    hint: "L'agent attend que tu valides son plan." },
  crashed: { label: "Arrêté sans finir", tone: "danger", icon: "!", group: "a_traiter", pulse: false,
    hint: "L'agent s'est arrêté sans rendre de réponse finale : continue-le ou relance-le." },
  launch_failed: { label: "Lancement échoué", tone: "danger", icon: "!", group: "a_traiter", pulse: false,
    hint: "L'agent n'a pas pu démarrer." },
  idle: { label: "Terminé", tone: "ok", icon: "✓", group: "termines", pulse: false,
    hint: "Terminé ; l'agent peut encore recevoir un message sans redémarrer." },
  finished: { label: "Terminé", tone: "ok", icon: "✓", group: "termines", pulse: false,
    hint: "L'agent a rendu sa réponse finale." },
  archived: { label: "Archivé", tone: "neutral", icon: "▪", group: "archives", pulse: false,
    hint: "Retiré de la liste ; restaurable." },
  unknown: { label: "État inconnu", tone: "neutral", icon: "·", group: "termines", pulse: false,
    hint: "" },
};

/**
 * Clé d'état canonique d'un agent à partir d'un node de /api/agents/tree (ou de tout objet
 * portant `state`, `phase`, `liveness`, `archived`, `interrupted`, `launch_failed`,
 * `suspect_dead`). `opts.hasLiveChildren` indique un agent fini dont des enfants tournent.
 * @returns {keyof AGENT_STATES}
 */
export function agentStateKey(n, opts = {}) {
  if (!n) return "unknown";
  if (typeof n === "string") n = { state: n };
  const state = String(n.state || n.status || "").toLowerCase();
  if (n.archived === true || state === "archived") return "archived";
  if (n.launch_failed || state === "launch_failed") return "launch_failed";
  if (state === "awaiting_input") return "awaiting_input";
  if (state === "awaiting_plan_validation") return "awaiting_plan_validation";
  if (n.liveness === "crashed" || n.interrupted === true || n.suspect_dead === true
      || state === "crashed" || state === "error" || state === "interrupted" || state === "killed") return "crashed";
  if (n.phase === "attente_modele") return "thinking";
  if (n.phase === "demarrage" || state === "provisioning" || state === "starting" || state === "launching") return "preparing";
  if (state === "waiting_children" || state === "orchestrating") return "orchestrating";
  if (state === "running") return "running";
  if (state === "idle") return opts.hasLiveChildren ? "orchestrating" : "idle";
  if (state === "finished" || state === "cli" || state === "done") return opts.hasLiveChildren ? "orchestrating" : "finished";
  return AGENT_STATES[state] ? state : "unknown";
}

/** Informations d'affichage d'un agent (node ou clé). @returns {StateInfo} */
export function agentState(nOrKey, opts) {
  const key = typeof nOrKey === "string" && AGENT_STATES[nOrKey] ? nOrKey : agentStateKey(nOrKey, opts);
  return { key, ...AGENT_STATES[key] };
}

/** L'agent est-il vivant (un poll rapide se justifie) ? */
export function isAgentActive(nOrKey) {
  return agentState(nOrKey).group === "en_cours";
}

// ---------------------------------------------------------------- tâches

/** Segments du Bureau (ordre d'affichage). */
export const TASK_SEGMENTS = [
  { key: "a_moi", label: "À moi" },
  { key: "en_cours", label: "En cours" },
  { key: "a_lancer", label: "À lancer" },
  { key: "archivees", label: "Archivées" },
];

/** @type {Record<string, {label:string, tone:string, icon:string, segment:string, rank:number, hint:string}>} */
export const TASK_STATUSES = {
  a_repondre: { label: "Attend ta réponse", tone: "warn", icon: "?", segment: "a_moi", rank: 0,
    hint: "Un agent de cette tâche t'a posé une question." },
  en_echec: { label: "Arrêté sans finir", tone: "danger", icon: "!", segment: "a_moi", rank: 1,
    hint: "L'agent s'est arrêté sans rendre de réponse finale : fais-le continuer, ou relance un agent neuf." },
  a_relire: { label: "À vérifier", tone: "ok", icon: "✓", segment: "a_moi", rank: 2,
    hint: "L'agent a rendu sa réponse finale : vérifie son travail, puis clos la tâche ou renvoie-la." },
  a_decider: { label: "À décider", tone: "warn", icon: "◆", segment: "a_moi", rank: 3,
    hint: "Un agent a fini en te laissant ce choix ; aucun agent n'attend." },
  en_cours: { label: "En cours", tone: "info", icon: "●", segment: "en_cours", rank: 4,
    hint: "Un agent travaille sur cette tâche." },
  brouillon: { label: "À lancer", tone: "neutral", icon: "○", segment: "a_lancer", rank: 5,
    hint: "Pas encore lancée : relis le brief, puis lance-la." },
  faite: { label: "Faite", tone: "ok", icon: "✓", segment: "archivees", rank: 6, hint: "" },
  abandonnee: { label: "Abandonnée", tone: "neutral", icon: "–", segment: "archivees", rank: 7, hint: "" },
};

// ---------------------------------------------------------------- lexique du serveur

/** Le lexique injecté par base.html ({entrees, motifs, tickets}), ou null (tests, page nue). */
function lexiqueInjecte() {
  try {
    const el = typeof document !== "undefined" && document.getElementById("bz-lexique");
    return el ? JSON.parse(el.textContent) : null;
  } catch (e) {
    return null;
  }
}

export const LEXIQUE = lexiqueInjecte();

/** Remplace les mots par défaut d'une table par ceux du serveur (clé par clé). */
function appliquerLexique(table) {
  const entrees = (LEXIQUE && LEXIQUE.entrees) || {};
  for (const [cle, info] of Object.entries(table)) {
    const e = entrees[cle];
    if (!e) continue;
    Object.assign(info, { label: e.mot || info.label, hint: e.aide || info.hint, tone: e.ton || info.tone, icon: e.icone || info.icon });
  }
}
appliquerLexique(AGENT_STATES);
appliquerLexique(TASK_STATUSES);

/** Mot, aide, ton et icône d'une entrée du lexique (clé de tâche, d'agent, ou autre) ; null si inconnue. */
export function entreeLexique(cle, parDefaut = null) {
  const e = LEXIQUE && LEXIQUE.entrees && LEXIQUE.entrees[cle];
  if (e) return { label: e.mot, hint: e.aide, tone: e.ton, icon: e.icone };
  const local = TASK_STATUSES[cle] || AGENT_STATES[cle];
  return local ? { label: local.label, hint: local.hint, tone: local.tone, icon: local.icon } : parDefaut;
}

/**
 * Clé de statut canonique d'une tâche. Accepte : une clé déjà canonique, ou une ligne de
 * /api/lignes (`statut` ∈ {en_cours, inactif, archive} + `raison`), ou une micro (`etat`).
 * @returns {keyof TASK_STATUSES}
 */
export function taskStatusKey(t) {
  if (!t) return "brouillon";
  if (typeof t === "string") return TASK_STATUSES[t] ? t : "brouillon";
  const statut = t.statut || t.status || "";
  const raison = t.raison || t.reason || "";
  if (TASK_STATUSES[statut] && statut !== "en_cours") return statut;
  if (statut === "archive") return raison === "abandonnee" ? "abandonnee" : "faite";
  if (statut === "en_cours") return "en_cours";
  if (statut === "inactif") {
    if (raison === "a_faire") return "brouillon";
    if (raison === "figee" || raison === "en_echec" || raison === "launch_failed") return "en_echec";
    if (TASK_STATUSES[raison]) return raison;
    return "brouillon";
  }
  const etat = t.etat || "";
  if (etat === "faite") return "faite";
  if (etat === "abandonnee") return "abandonnee";
  if (etat === "lancee") return "en_cours";
  if (t.decision) return "a_decider";
  return "brouillon";
}

/** Informations d'affichage d'une tâche. */
export function taskStatus(t) {
  const key = taskStatusKey(t);
  return { key, ...TASK_STATUSES[key] };
}

// ---------------------------------------------------------------- badge

/**
 * Construit le badge d'état standard (ds.css `.badge`).
 * @param {{label:string, tone:string, icon:string, pulse?:boolean, hint?:string}} info
 *   résultat de agentState() / taskStatus()
 * @param {{compact?:boolean, title?:string}} [opts] compact : icône seule, libellé en
 *   infobulle + lecteur d'écran — SAUF tons warn/danger qui gardent leur libellé.
 * @returns {HTMLSpanElement}
 */
export function badge(info, opts = {}) {
  const b = document.createElement("span");
  b.className = `badge${opts.compact ? " badge--compact" : ""}${opts.text ? " badge--text" : ""}`;
  b.dataset.tone = info.tone;
  if (info.key) b.dataset.state = info.key;
  if (info.pulse) b.dataset.pulse = "true";
  b.title = opts.title || (info.hint ? `${info.label} — ${info.hint}` : info.label);
  const icon = document.createElement("span");
  icon.className = "badge__icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = info.icon;
  const label = document.createElement("span");
  label.className = "badge__label";
  label.textContent = info.label;
  b.append(icon, label);
  return b;
}

export default { AGENT_STATES, AGENT_GROUPS, TASK_STATUSES, TASK_SEGMENTS, agentStateKey, agentState,
  isAgentActive, taskStatusKey, taskStatus, badge };
