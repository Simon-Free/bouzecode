# routes/work/micros/

## Purpose
Blueprint `micros_api` : les routes du Bureau sur les chantiers (macro-tâches) et les tâches
(micro-tâches) — modèle de `docs/bureau-todo-modele-et-api.md` §10.

## Usage
- `lignes_et_chantiers.py` — `GET /api/lignes[/<id>]`, `/api/macros*`
- `taches.py` — `/api/micros` (CRUD), précisions, `pret`, `etat`, `classer`
- `gestes.py` — `lancer`, `prompt`, `relancer`, `arreter`, `passages/<ticket>/integrer|suites`
- `_commun.py` — erreur à la forme unique, refus d'un geste, chantier/tâche ou 404
