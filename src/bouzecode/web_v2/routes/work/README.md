# routes/work/

## Purpose
Endpoints du travail : projets, tickets, flotte d'agents et agent-builder.
Signatures exactes : `GET /api/schema` (dérivé de `app.url_map`).

## Usage
- `projects.py` — `GET /api/projects`, `GET /api/projects/logical`, `POST /api/projects`,
  `PATCH|DELETE /api/projects/<slug>`, `GET /api/projects/<slug>/agents`, `GET /api/models`
- `tickets.py` — `GET|POST /api/projects/<slug>/tickets`, `GET /api/tickets/<slug>/<id>`,
  `POST /api/tickets/<slug>/<id>/launch|comments|validate|integrate|completed|done|archive|unarchive`,
  `GET /api/tickets/<slug>/<id>/results`
- `fleet.py` — `POST /api/dispatch` (**la voie de lancement de l'UI** : crée le ticket ET
  lance l'agent ; `isolation` = `shared` | `worktree` | `worktree+venv`, `defer` répond avant
  le spawn), `POST /api/agent/message`, `GET /api/agents/tree`
- `builder.py` — profils, skills, plugins, catalogue d'agents (`/api/builder/*`,
  `/api/profiles*`, `/api/skills*`, `/api/plugins*`, `/api/agents/catalog·install·import·export`)

Il n'y a plus de chaîne automatique travail → validation → merge : `/completed` ne fait que
clore le run et signaler un crash ; validation et merge sont déclenchés explicitement
(`/validate`, `/integrate`).
