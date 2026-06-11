# services/sessions/

## Purpose
Accès aux sessions (JSON de session = source de vérité) et analyse par appel LLM.

## Usage
- `store.py` — clés `agent/<id>` / `daily/<date>/<fichier>`, `resolve()`, `list_sessions()`
  (cache méta par mtime), `agent_status()` (process + IPC), `load_session_json()`
- `analysis.py` — `turn_table()` : par appel LLM durée/tokens/cache/coût ;
  `turn_detail()` : payload annoté cached/new-cache/fresh + réponse rendue.
  Réutilise `web.context_viewer` (v1) et les dumps `debug_payloads/<session>/turns.jsonl`
