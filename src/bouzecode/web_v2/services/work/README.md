# services/work/

## Purpose
Le modèle "travail" : projets ouverts dans l'UI et tickets par projet.

## Usage
- `projects.py` — registre `~/.bouzecode/web_v2/projects.json` : `list_projects()`,
  `add_project()`, `find()`, `agents_of()` (agents web dont cwd ⊂ path),
  `overview()` (compteurs d'actions requises par projet pour la home)
- `tickets.py` — `~/.bouzecode/web_v2/tickets/<slug>.json` : CRUD tickets,
  `add_run()` (kind work|validate_tests|validate_refacto), `add_comment()`,
  `refresh_verdicts()` (parse `VERDICT: OK|KO` du dernier message assistant),
  `derive_status()` (en cours → à relire → validé → terminé), `VALIDATORS`
