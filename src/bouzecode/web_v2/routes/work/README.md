# routes/work/

## Purpose
Endpoints projets (ouvrir, overview avec compteurs d'actions) et tickets
(créer & lancer, commenter/follow-up, valider tests/refacto, terminer).

## Usage
- `projects.py` — `GET/POST/DELETE /api/projects`, `GET /api/projects/<slug>/agents`, `GET /api/models`
- `tickets.py` — `GET/POST /api/projects/<slug>/tickets`,
  `POST /api/tickets/<slug>/<id>/launch|comments|validate|done`
