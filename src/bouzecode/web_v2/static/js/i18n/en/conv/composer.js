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
window.i18n.register("en", {
  "composer.pick_one": "pick one",

  // Descriptions des trois niveaux d'isolation.
  "composer.isolation.shared_desc": "Nothing provisioned: the agent works in the main repository. "
    + "The fastest option — for a read-only agent, a short task, or the only writer.",
  "composer.isolation.worktree_desc": "A dedicated git worktree, WITHOUT a venv. As soon as several "
    + "agents write to the same repository in parallel. Practically free.",
  "composer.isolation.worktree_venv_desc": "A dedicated worktree AND venv. Only when the agent touches "
    + "dependencies (a full uv sync: ~30 s of startup).",

  // Ouvrir un projet depuis l'interface (POST /api/projects). Les refus viennent du
  // serveur, qui est monolingue : son message s'affiche tel quel, comme les noms de projets.
  "composer.add_project": "Add a project:",
  "composer.project_name": "name",
  "composer.project_path": "absolute path",
  "composer.project_description": "description (optional)",
  "composer.add": "Add",
  "composer.name_and_path_required": "Both the name and the path are required.",

  // Échecs du lancement.
  "composer.project_required": "Project required — suggestions:",
  "composer.needs_project": "Pick a project above before starting the conversation.",
  "composer.network_retry": "network: try again.",
});
