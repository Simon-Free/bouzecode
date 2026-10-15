# routes/work/

## Purpose
Endpoints du travail hors API des tickets : projets, flotte d'agents, Bureau et agent-builder.
Signatures exactes : `GET /api/schema` (dérivé des routes).

## Usage
- `projects.py` — `GET|POST /api/projects`, `PATCH|DELETE /api/projects/<slug>`,
  `/api/projects/dismissed`, `GET /api/models`
- Tickets et agents : voir `routes/tickets_api/` (API cible §6).
- `fleet.py` — `GET /api/agents/tree` (arbre servi au front), `GET /api/agents/activity`
- `micros.py`, `tasks.py`, `inbox.py`, `signalements.py`, `decisions.py`, `assistant.py` — le Bureau
- `builder.py` — profils, skills, plugins, catalogue d'agents (`/api/builder/*`,
  `/api/profiles*`, `/api/skills*`, `/api/plugins*`, `/api/agents/catalog·install·import·export`)

Aucun automatisme décisionnel côté serveur : la fin d'un run (`/internal/runs/<id>/ended`) ne
fait que le clore ; intégrer, clore, rouvrir et nettoyer sont des gestes explicites du manager
ou de l'humain. Un conflit d'intégration est renvoyé tel quel.
