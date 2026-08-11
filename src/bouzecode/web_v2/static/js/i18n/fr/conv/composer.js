// Zone « composer » de la page Conversations : les trois bannières d'options (type d'agent,
// projet, environnement) et les échecs de lancement, tels que le JavaScript les CONSTRUIT.
// Le chrome figé du gabarit (placeholder de la barre, « Options », « Projet : ») vit dans
// `common.js` sous `conv.*` : il est écrit dans le HTML servi, pas composé ici.
//
// CE QUI N'EST PAS ICI, ET POURQUOI. Les noms de projets viennent de /api/projects et sont
// des données de l'utilisateur ; les noms et descriptions de typologies viennent d'un
// catalogue ouvert (/api/typologies, alimenté par les profils YAML de chacun). Ni les uns
// ni les autres ne sont traduits — le serveur reste monolingue et ces libellés lui
// appartiennent. Les codes d'isolation (`shared`, `worktree`, `worktree+venv`) sont le
// vocabulaire de l'API, pas des mots d'interface : ils s'affichent tels quels.
window.i18n.register("fr", {
  "composer.pick_one": "à choisir",

  // Descriptions des trois niveaux d'isolation.
  "composer.isolation.shared_desc": "Rien de provisionné : l'agent travaille dans le dépôt "
    + "principal. Le plus rapide — pour un agent en lecture seule, une tâche courte, ou le "
    + "seul écrivain.",
  "composer.isolation.worktree_desc": "Worktree git dédié, SANS venv. Dès que plusieurs agents "
    + "écrivent en parallèle sur le même dépôt. Quasi gratuit.",
  "composer.isolation.worktree_venv_desc": "Worktree ET venv dédiés. Uniquement si l'agent touche "
    + "aux dépendances (uv sync complet : ~30 s de lancement).",

  // Ouvrir un projet depuis l'interface (POST /api/projects). Les refus viennent du
  // serveur, qui est monolingue : son message s'affiche tel quel, comme les noms de projets.
  "composer.add_project": "Ajouter un projet :",
  "composer.project_name": "nom",
  "composer.project_path": "chemin absolu",
  "composer.project_description": "description (facultatif)",
  "composer.add": "Ajouter",
  "composer.name_and_path_required": "Le nom et le chemin sont tous les deux requis.",

  // Échecs du lancement.
  "composer.project_required": "Projet requis — suggestions :",
  "composer.needs_project": "Choisis un projet ci-dessus avant de lancer la conversation.",
  "composer.network_retry": "réseau : réessaie.",
});
