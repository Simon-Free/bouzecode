# routes/tickets_api/

## Purpose
L'API cible des tickets (spec ticketing §6, lots L3/L5) : les handlers parsent, appellent
`services/work/api_tickets`, sérialisent ; le corps attendu d'une mutation est déclaré par
`@corps_attendu` (`schema/`). Tout refus est un `Refus` (`services/erreurs.py`) rendu à la forme unique
`{"error": {"code", "message", "details"}}`.

## Usage
- `tickets.py` — `GET|POST /api/projects/<slug>/tickets` (liste pure paginée, création 201,
  `Idempotency-Key`), `GET|PATCH …/<id>`, `GET|POST …/<id>/events`, `GET …/<id>/runs`
- `gestes.py` — `POST …/<id>/runs` (202), `/messages`, `/answer`, `/interrupt`, `/stop`
- `livraison.py` — `POST …/<id>/delivery/refresh`, `/harvest`, `/integrate` (202), `GET …/diff`,
  `GET /api/projects/<slug>/occupation`
- `rangement.py` — `POST …/close|reopen`, `PUT …/archived`, `POST …/cleanup`
- `agents.py` — `GET /api/agents`, `GET /api/agents/<id>[/children]`, `POST /api/agents`,
  `POST /api/agents/<id>/messages|stop|interruptions`
- `interne.py` — `POST /internal/runs/<agent_id>/ended` (jeton propre au run)
- `_commun.py` — corps JSON lu une fois, ticket ou 404/409, réponse JSON lisible

Les alias dépréciés des anciennes routes (dispatch, tickets sans projet dans le chemin,
continue, kill…) ont été retirés au lot L6 ; un test statique
(`tests/test_l6_routes_retirees.py`) échoue si l'une d'elles réapparaît dans le code.
