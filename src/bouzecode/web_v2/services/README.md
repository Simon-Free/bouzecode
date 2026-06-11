# Services — Logique métier web_v2 (sans Flask)

Couche service : toute la logique métier, séparée des routes Flask. Testable indépendamment.

## Fichiers racine

| Fichier | Rôle |
|---------|------|
| `file_service.py` | Explorateur de fichiers projet (listing, lecture, pygments) |
| `message_view.py` | Rendu des messages de session (Markdown, tool_calls, thinking blocks) |

## Sous-dossiers

| Dossier | Contenu |
|---------|---------|
| `sessions/` | Chargement, analyse et coûts des sessions JSON |
| `work/` | Projets, tickets et résultats (gestion du workflow) |

### sessions/

| Fichier | Rôle |
|---------|------|
| `store.py` | Chargement et listing des fichiers session JSON |
| `analysis.py` | Analyse par tour : tokens, cache, outils utilisés |
| `costs.py` | Agrégation des coûts par modèle et par session |

### work/

| Fichier | Rôle |
|---------|------|
| `projects.py` | CRUD projets (slug, path, config) |
| `tickets.py` | CRUD tickets + runs (work, validate_tests, validate_refacto) |
| `results.py` | Extraction résultats d'un run (patch, verdict, output) |

## Points d'entrée

- `store.py` → `list_sessions()`, `load_session(key)` : accès aux sessions
- `tickets.py` → `create_ticket()`, `add_run()` : workflow tickets
- `costs.py` → `aggregate_costs(session)` : rapport de coûts
