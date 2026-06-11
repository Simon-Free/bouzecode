# Routes — Blueprints API Flask web_v2

Endpoints REST exposés par le serveur web_v2. Chaque fichier = un Blueprint Flask.

## Fichiers racine

| Fichier | Rôle |
|---------|------|
| `__init__.py` | Enregistrement de tous les blueprints |
| `files.py` | `GET /api/files/<path>` — explorateur de fichiers projet |
| `sessions.py` | `GET /api/sessions/...` — listing, détail, turns, blocks, coûts |

## Sous-dossier work/

| Fichier | Rôle |
|---------|------|
| `projects.py` | `GET/POST /api/projects/...` — CRUD projets |
| `tickets.py` | `GET/POST /api/projects/<slug>/tickets/...` — CRUD tickets, lancement, validation, commentaires |

## Endpoints principaux

### Sessions
- `GET /api/sessions` — liste des sessions récentes
- `GET /api/sessions/<key>` — détail d'une session (meta + status)
- `GET /api/sessions/<key>/turns` — analyse par tour (tokens, cache, outils)
- `GET /api/sessions/<key>/blocks` — messages formatés pour affichage
- `GET /api/sessions/<key>/costs` — rapport de coûts agrégé

### Work (projets + tickets)
- `GET /api/projects` — liste des projets
- `POST /api/projects/<slug>/tickets` — créer un ticket (+ lancer agent)
- `POST /api/tickets/<slug>/<id>/launch` — relancer un ticket
- `POST /api/tickets/<slug>/<id>/validate` — lancer validation tests/refacto
- `POST /api/tickets/<slug>/<id>/comments` — ajouter commentaire/follow-up
- `POST /api/tickets/<slug>/<id>/done` — toggle done
