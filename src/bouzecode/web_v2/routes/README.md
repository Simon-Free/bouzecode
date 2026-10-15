# routes/

## Purpose
Blueprints Flask du serveur web_v2, tous enregistrés par `register_routes(app)` (`__init__.py`).
Un handler parse la requête, appelle un service, sérialise : la logique vit dans `services/`.

**La liste des endpoints qui fait foi est `GET /api/schema`**, DÉRIVÉE de `app.url_map` : la
description d'une route est le docstring de sa vue, son corps attendu est déclaré à côté d'elle
par `@corps_attendu` (`../schema/`). Aucune table écrite à la main ; gardes :
`../tests/test_schema_coverage.py` (100 % des routes décrites) et
`../tests/test_skill_web_api_a_jour.py` (la skill `web-api.md` est régénérée du schéma).

**Erreurs** : forme UNIQUE `{"error": {"code", "message", "details"?}}`, code HTTP >= 400. Un
service lève `services/erreurs.Refus` ; `_errors.installer` le sérialise, comme les refus de la
machine à états, les erreurs du protocole (404/405 sous `/api/`) et les 500 (journalisées).
Garde : `../tests/test_erreurs_forme_unique.py`.

## Usage
| Fichier | Blueprint | Domaine |
|---------|-----------|---------|
| `search.py` | `search_bp` | `GET /api/search?q=&scope=open\|all` |
| `typologies.py` | `typologies_bp` | `GET /api/typologies?project=<slug>` |
| `version.py` | `version_bp` | `GET /api/version` — dérive SHA boot vs HEAD + source du disque |
| `env_sanity.py` | `env_sanity_bp` | `GET /api/env-sanity` (+ `POST …/recheck`) — verdict env API |
| `server.py` | `server_bp` | `POST /api/server/restart`, `…/shutdown` |
| `enquete.py` | `enquete_bp` | page `/enquete/<agent>` et `/api/enquete/*` (tours, payloads, note) |
| `schema.py` | `schema_bp` | `GET /api/schema`, `GET /api/lexique` |
| `_errors.py` | — | `erreur(code, message, status, **details)` et `installer(app)` (gestionnaires d'erreurs) |
| `_body.py` | — | `json_body(request)` : décodage utf-8 / utf-8-sig / latin-1 |

Les lancements passent par `services/work/api_tickets/garde.exiger()` : environnement KO → 503
`env_indisponible`, aucun agent n'est spawné.

## Subfolders
| Folder | Description |
|--------|-------------|
| `sessions/` | Sessions et conversations : liste, rangement, blocs du fil (polling), analyse des tours, vues |
| `tickets_api/` | API cible des tickets et des agents (spec §6), route interne de fin de run |
| `work/` | Projets, flotte (arbre, activité), Bureau (micros, inbox, tâches), agent-builder |
