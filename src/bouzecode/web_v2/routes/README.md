# routes/

## Purpose
Blueprints Flask du serveur web_v2. Un fichier = un blueprint, tous enregistrés par
`register_routes(app)` (`__init__.py`).

**La liste des endpoints qui fait foi est `GET /api/schema`** : elle est DÉRIVÉE de
`app.url_map`, donc elle ne peut ni décrire une route disparue ni ignorer une route
ajoutée. Ne recopie pas de table d'endpoints ici — interroge le schéma. Descriptions
écrites à la main : `../api_descriptions.py` ; gardes anti-dérive :
`../tests/test_schema_coverage.py`.

## Usage
| Fichier | Blueprint | Domaine |
|---------|-----------|---------|
| `sessions.py` | `sessions_bp` | sessions, conversations, cycle de vie des agents (`/api/sessions/*`, `/api/conversations/*`, `/api/agents/launch·continue·kill·interrupt`) |
| `search.py` | `search_bp` | `GET /api/search?q=&scope=open\|all` |
| `typologies.py` | `typologies_bp` | `GET /api/typologies?project=<slug>` |
| `version.py` | `version_bp` | `GET /api/version` — dérive SHA boot vs HEAD courant + source du disque (état caché 10 s) |
| `env_sanity.py` | `env_sanity_bp` | `GET /api/env-sanity` — verdict env API figé au boot |
| `interrupted.py` | `interrupted_bp` | `GET /api/interrupted`, `POST /api/interrupted/dismiss` |
| `_body.py` | — | `json_body(request)` : décodage utf-8 / utf-8-sig / latin-1. **À utiliser partout** plutôt que `request.get_json` (corps accentué envoyé par PowerShell → 400 sinon). |

Les endpoints qui lancent un agent appellent d'abord `api_sanity.require_api_sanity()` :
env API KO au boot → 503 immédiat, aucun agent n'est spawné.

## Subfolders
| Folder | Description |
|--------|-------------|
| `work/` | Projets, tickets, flotte (`POST /api/dispatch`) et agent-builder |
