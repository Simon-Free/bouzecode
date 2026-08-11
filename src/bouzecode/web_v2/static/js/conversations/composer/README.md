# composer/

## Purpose
La barre « nouvelle conversation » : ses bannières de choix, le lancement en `defer`
avec rendu optimiste, et le talonnage du démarrage jusqu'à ce que l'agent soit né.

## Usage
| Fichier | Rôle |
|---------|------|
| `launch.js` | `POST /api/dispatch`, node optimiste « starting », câblage de la barre |
| `retarget.js` | rebranchement `optimistic:` / `launching/` → `agent/<id>`, `chaseLaunch` |
| `typology.js` | bannière « type d'agent » (`/api/typologies`) |
| `project.js` | bannière « projet » (`/api/projects`), formulaire d'ouverture d'un projet, suggestions `needs_project` |
| `isolation.js` | bannière « environnement » : shared / worktree / worktree+venv |

Les trois bannières exportent leur sélection en lien vivant (`selectedTypology`,
`selectedProject`, `selectedIsolation`) ; `launch.js` les lit au moment du dispatch.
