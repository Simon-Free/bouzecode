# web_v2 — BouzéqUI v2

## Purpose
UI web orientée projets pour piloter des agents bouzecode. Principe : **on ne parse
jamais le stdout** — tout est rendu serveur depuis les JSON structurés (session JSON,
IPC, dumps de payload). Spécification complète : `SPEC.md` (parcours P1–P7).

## Usage
```
python -m bouzecode.web_v2 [--port 5056]      # ou bouzequi2, ou bouzeui.ps1 -v2
```
Pages : `/` (projets + compteurs d'actions requises), `/p/<slug>` (agents, tickets :
créer & lancer, valider tests/refacto, commentaires/follow-up), `/sessions/<key>`
(conversation, diffs, onglet Tours : tokens/cache/coût par appel LLM + drill-down
payload annoté cached/new-cache/fresh), `/files` (explorateur pygments par projet).
API LLM-friendly : `GET /api/schema`.

Réutilise `web.runner`/`ipc`/`pending` et `web.context_viewer` (v1).

## Subfolders
| Folder | Description |
|--------|-------------|
| `routes/` | Blueprints API (sessions/fichiers + work/: projets, tickets) |
| `services/` | Logique métier sans Flask (sessions/, work/, rendu messages, fichiers) |
| `templates/` | 5 pages Jinja (base, home, project, session, files) |
| `static/` | CSS thème sombre + `js/` vanilla (un fichier par page + turns) |
