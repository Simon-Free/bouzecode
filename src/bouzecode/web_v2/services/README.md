# Services — Logique métier web_v2 (sans Flask)

Couche service : toute la logique métier, séparée des routes Flask. Testable indépendamment.

## Fichiers racine

| Fichier | Rôle |
|---------|------|
| `erreurs.py` | `Refus(code, message, status, **details)` : le refus métier UNIQUE des services ; les routes le sérialisent (un service n'importe jamais `routes/`) |
| `file_service.py` | Diffs HTML des `file_snapshots` d'une session (onglet « fichiers modifiés ») |
| `message_view.py` | Rendu des messages de session (Markdown, tool_calls, thinking blocks) |
| `horodatage.py` | Dates du store et de l'API : écriture UTC unique (`maintenant_iso`), lecture tolérante des dates locales héritées (`lire_instant`, `age_s`, `cle_chrono`) — voir `work/README.md` |

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
| `tickets.py` | CRUD tickets + runs (kind : work, validate, merge) |
| `results.py` | Extraction résultats d'un run (patch, verdict, output) |

## Points d'entrée

- `store.py` → `list_sessions()`, `load_session(key)` : accès aux sessions
- `tickets.py` → `create_ticket()`, `add_run()` : workflow tickets
- `costs.py` → `aggregate_costs(session)` : rapport de coûts
