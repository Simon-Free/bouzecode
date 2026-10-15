// [desc] État partagé du Bureau : dernières données serveur (tâches, inbox, dépôts, profils) + préférences d'affichage mémorisées (mode de tri, replis, dépliages). [/desc]
//
// Un seul objet mutable, lu par tous les modules de rendu. Les préférences (mode de tri,
// chantiers repliés, archives ouvertes, tâches dépliées) survivent au rechargement via
// localStorage — toujours dans un try/catch : navigation privée = préférences non gardées.

const PREFS_KEY = "bz.bureau.prefs";

/** Les deux façons de ranger le Bureau (SPEC §4.3). */
export const MODES = [
  { key: "statut", label: "Statut" },
  { key: "chantier", label: "Chantier" },
];

function readPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    return raw ? JSON.parse(raw) || {} : {};
  } catch (_) {
    return {};
  }
}

const saved = readPrefs();

export const state = {
  /** Réponse de /api/lignes (null tant que rien n'est chargé). */
  lignes: null,
  /** Réponse de /api/inbox. */
  inbox: null,
  /** [{slug, name, description}] */
  projets: [],
  /** [{name, description}] */
  profils: [],
  /** « statut » (défaut) ou « chantier ». */
  mode: MODES.some((m) => m.key === saved.mode) ? saved.mode : "statut",
  recherche: "",
  /** ids de chantiers repliés */
  replies: new Set(saved.replies || []),
  /** clés des blocs d'archives ouverts (« statut », « chantiers », ou un id de chantier) */
  archivesOuvertes: new Set(saved.archivesOuvertes || []),
  /** ids de tâches dépliées */
  deplies: new Set(saved.deplies || []),
};

export function savePrefs() {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify({
      mode: state.mode, replies: [...state.replies], archivesOuvertes: [...state.archivesOuvertes],
      deplies: [...state.deplies].slice(-30),
    }));
  } catch (_) {
    // Stockage indisponible (navigation privée) : les préférences vivent le temps de l'onglet.
    state.prefsNonGardees = true;
  }
}

/** Demande un nouveau rendu du Bureau — écouté par main.js. */
export function demanderRendu() {
  window.dispatchEvent(new CustomEvent("bz:render"));
}

/** Change de mode de tri (mémorisé) ; `rendre:false` quand l'appelant rafraîchit lui-même. */
export function choisirMode(k, { rendre = true } = {}) {
  if (!MODES.some((m) => m.key === k)) return;
  state.mode = k;
  savePrefs();
  if (rendre) demanderRendu();
}

/** Ouvre / ferme un bloc d'archives (`cle` : « statut », « chantiers » ou id de chantier). */
export function basculerArchives(cle, ouvrir) {
  const voulu = ouvrir === undefined ? !state.archivesOuvertes.has(cle) : ouvrir;
  if (voulu) state.archivesOuvertes.add(cle); else state.archivesOuvertes.delete(cle);
  savePrefs();
  demanderRendu();
}

/** Pose la réponse de /api/lignes en annotant AUSSITÔT chaque tâche de son chantier : le mode
 *  Chantier rend `c.lignes` directement, et une tâche non annotée s'affichait « Sans chantier »
 *  (infobulle) et perdait les dépôts de son chantier au lancement. */
export function poserLignes(d) {
  state.lignes = d;
  appliquerReprises(toutesLesTaches());
}

// ---------------------------------------------------------------- reprises (optimiste)

const REPRISE_MS = 30000;
const ACTIFS = new Set(["en_cours", "a_repondre"]);
/** id de tâche -> échéance : l'agent vient d'être relancé (même agent) ou prié de continuer. */
const reprises = new Map();

/** Juste après « Renvoyer avec un retour » / « Continuer » : la tâche s'affiche « En cours »
 *  tout de suite (l'agent met quelques secondes à reprendre son tour, et la tâche restait
 *  « À vérifier » sans geste « consigne » pendant ce temps). Levé dès que le serveur confirme. */
export function marquerReprise(id) {
  reprises.set(id, Date.now() + REPRISE_MS);
  appliquerReprises(toutesLesTaches());
  demanderRendu();
}

function appliquerReprises(taches) {
  const maintenant = Date.now();
  for (const t of taches) {
    const echeance = reprises.get(t.id);
    if (!echeance) continue;
    if (t._reprise) continue; // déjà habillé par nous : ce n'est pas le serveur qui confirme
    if (ACTIFS.has(t.statut_ui) || echeance < maintenant) { reprises.delete(t.id); continue; }
    Object.assign(t, { statut_ui: "en_cours", segment: "en_cours", libelle_statut: "Reprise…", agent_actif: true, _reprise: true,
      activite: t.activite || "L'agent reprend son travail…" });
  }
}

/** Toutes les tâches, à plat, chacune annotée de son chantier (`_chantier`). */
export function toutesLesTaches() {
  const d = state.lignes;
  if (!d) return [];
  const out = [];
  for (const c of d.chantiers || []) for (const t of c.lignes || []) out.push(Object.assign(t, { _chantier: c }));
  for (const t of d.non_rattachees || []) out.push(Object.assign(t, { _chantier: null }));
  return out;
}

export function tacheParId(id) {
  return toutesLesTaches().find((t) => t.id === id) || null;
}

export function chantierParId(id) {
  return ((state.lignes && state.lignes.chantiers) || []).find((c) => c.macro_id === id) || null;
}

/** Un agent tourne-t-il quelque part sur le Bureau (→ cadence de poll rapide) ? */
export function agentsActifs() {
  return toutesLesTaches().some((t) => t.agent_actif || t.statut_ui === "en_cours");
}

export function nomProjet(slug) {
  const p = state.projets.find((x) => x.slug === slug);
  return p ? (p.name || p.slug) : slug;
}
