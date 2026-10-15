# routes/sessions/

## Purpose
Blueprint `sessions_api` : lire une session ou une conversation (LECTURE PURE), et ranger les
conversations (archiver, purger les tests, restaurer).

## Usage
- `liste.py` — `GET /api/sessions`, `/api/sessions/grep`, `…/<key>/download`, file de messages d'un agent
- `conversations.py` — `/api/conversations/*` (candidats de test, purge, archivage), restauration
- `blocs.py` (+ `blocs_rendu.py`) — `GET /api/sessions/<key>/blocks`, l'endpoint de polling du fil
- `analyse.py` — `…/turns`, `…/costs`, `…/turns/<n>[/view|/context]`, `…/calls/<id>`
- `vues.py` — `…/overview`, `…/partial`, `…/recap`, `…/files`
- `_commun.py` — session ou 404, JSON ou texte selon `?json`
