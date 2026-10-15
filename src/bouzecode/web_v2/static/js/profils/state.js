// [desc] Profils : état partagé de la page (catalogue, profils, sélection) et règles pures (préréglages, noms). [/desc]
//
// Module feuille : aucun accès réseau, aucun DOM. Les autres modules de static/js/profils/
// lisent et mutent `S` ; les fonctions pures ci-dessous sont testées par vitest
// (tests/js/profils.state.test.js).

/** État de la page. `current.mode` : "new" (non enregistré), "edit" (profil global), "readonly" (fourni). */
export const S = {
  catalog: { tools: [], skills: [], hooks: [], plugins: [] },
  catalogLoaded: false,
  agents: [],
  models: [],
  current: { mode: "new", name: "", basedOn: "", missing: { tools: [], skills: [] } },
};

/** Même règle que le serveur (profile_io.NAME_RE). */
export const NAME_RE = /^[a-z0-9][a-z0-9_-]*$/;

/** Outils d'orchestration : ce qui distingue « Orchestration » de « Code ». */
export const ORCHESTRATION_TOOLS = new Set([
  "Agent", "MessageAgent", "SendMessage", "CheckAgentResult", "ListAgentTasks", "ListAgentTypes",
  "Fleet", "LancerAgent",
]);

export const PRESETS = [
  { key: "lecture", label: "Lecture seule", hint: "Lit et cherche, ne modifie rien." },
  { key: "code", label: "Code", hint: "Lit, écrit, exécute : tout sauf lancer d'autres agents." },
  { key: "orchestration", label: "Orchestration", hint: "Tout, y compris lancer et piloter des sous-agents." },
  { key: "perso", label: "Personnalisé", hint: "Ta propre sélection d'outils." },
];

/** Outils sélectionnables (hors outils système, toujours actifs). */
export function selectableTools(catalog) {
  return (catalog.tools || []).filter((t) => !t.system);
}

/** Les noms d'outils d'un préréglage, calculés depuis le catalogue réel. */
export function presetTools(key, catalog) {
  const tools = selectableTools(catalog);
  if (key === "lecture") return tools.filter((t) => t.read_only).map((t) => t.name);
  if (key === "code") return tools.filter((t) => !ORCHESTRATION_TOOLS.has(t.name)).map((t) => t.name);
  if (key === "orchestration") return tools.map((t) => t.name);
  return null;
}

/** Quel préréglage correspond exactement à cette sélection ? "perso" sinon. */
export function presetOf(selected, catalog) {
  const want = new Set(selected);
  for (const key of ["lecture", "code", "orchestration"]) {
    const names = presetTools(key, catalog);
    if (names.length === want.size && names.every((n) => want.has(n))) return key;
  }
  return "perso";
}

/**
 * Outils d'un profil tel que chargé : liste vide = « aucune restriction » (tous les outils),
 * et les outils système sont retirés (ils sont toujours actifs, jamais une sélection).
 */
export function toolsOfProfile(profile, catalog) {
  const system = new Set((catalog.tools || []).filter((t) => t.system).map((t) => t.name));
  const tools = (profile.tools || []).filter((n) => !system.has(n));
  if (!tools.length) return selectableTools(catalog).map((t) => t.name);
  return tools;
}

/** Nom libre dérivé de `base` : « base-copie », « base-copie-2 »… jamais un nom déjà pris. */
export function copyName(base, taken) {
  const root = `${(base || "profil").replace(/-copie(-\d+)?$/, "")}-copie`;
  if (!taken.has(root)) return root;
  for (let i = 2; i < 1000; i++) if (!taken.has(`${root}-${i}`)) return `${root}-${i}`;
  return `${root}-${Date.now()}`;
}

/** Message d'erreur du champ nom, ou "" s'il est valide. */
export function nameProblem(name, { taken, isNew }) {
  if (!name) return "Donne un nom au profil.";
  if (!NAME_RE.test(name)) return "Minuscules, chiffres, - et _ uniquement (sans espace ni accent).";
  if (isNew && taken.has(name)) return `Un profil « ${name} » existe déjà : choisis un autre nom.`;
  return "";
}

/** Estimation grossière des tokens d'un texte (≈ 4 caractères par token). */
export function estimateTokens(text) {
  return Math.ceil((text || "").length / 4);
}

/** Libellé d'une taille en tokens : « 12 400 tokens ». */
export function formatTokens(n) {
  return `≈ ${n.toLocaleString("fr-FR")} tokens`;
}
