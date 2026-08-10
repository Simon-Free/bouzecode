# web_v2 — BouzéqUI v2

## Purpose
UI web pour piloter une flotte d'agents bouzecode. Principe : **on ne parse jamais le
stdout** — tout est rendu serveur depuis les JSON structurés (session JSON, IPC, dumps de
payload). Spécification complète : `SPEC.md` (parcours P1–P13).

## Usage
```
python -m bouzecode.web_v2 [--port 5056]      # ou bouzequi2, ou bouzeui.ps1 -v2
```
Pages : `/` → redirige vers `/conversations` (boîte de réception : conversations racines,
attentes d'input en tête, sous-agents en onglets ; la barre de lancement demande un projet
explicite), `/sessions/<key>` (conversation, diffs, onglet Tours : tokens/cache/coût par
appel LLM + drill-down payload annoté cached/new-cache/fresh), `/agent-builder` (composer
un agent : outils/skills/hooks + system prompt calculé).

Les pages web projets (`/projects`, `/p/<slug>`) et l'explorateur de fichiers (`/files`)
ont été retirés — voir SPEC.md (P1, P6). Les API `/api/projects*` et `/api/tickets*`
restent servies : `/conversations` et les agents les consomment.

API LLM-friendly : `GET /api/schema` — **dérivé de `app.url_map`**, jamais saisi à la main,
donc toujours d'accord avec les routes réellement enregistrées.

Le cycle de vie des agents (`runner`, `ipc`, `pending`) et l'analyse de payload
(`context_viewer`) vivent dans `runtime/` : le paquet `bouzecode.web` (v1) a été supprimé.

## Subfolders
| Folder | Description |
|--------|-------------|
| `routes/` | Blueprints API (sessions/recherche + work/: projets, tickets, flotte, builder) |
| `services/` | Logique métier sans Flask (sessions/, work/, skills, profils, plugins, rendu messages) |
| `runtime/` | Cycle de vie des agents (runner, ipc, pending, warmpool) + rendu HTML et context_viewer |
| `templates/` | Pages Jinja (base, conversations, session, agent_builder) |
| `static/` | CSS thème sombre, `js/` vanilla (un fichier par page) et `vendor/monaco/` (aucun CDN) |
