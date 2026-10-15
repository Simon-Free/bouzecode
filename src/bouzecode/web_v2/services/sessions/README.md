# services/sessions/

## Purpose
Accès aux sessions (JSON de session = source de vérité) et analyse par appel LLM.

## Usage
- `store.py` — clés `agent/<id>` / `daily/<date>/<fichier>`, `resolve()`, `list_sessions()`,
  `agent_status()` (process + IPC), `load_session_json()`
- `meta_index.py` — index de méta par mtime : `memoized_meta()` (memo process devant le
  fichier `index_cache.json`), `merge_into_file()`, `sweep_orphan_tmp()` (les `.tmp` laissés
  par un serveur tué entre l'écriture et le `replace` — 70 relevés sur le poste ; balayés au
  boot). Sans l'index, un listing re-décode jusqu'à 772 Mo de JSON de session (mesuré : 55 s
  pour un seul `GET /api/sessions`)
- `empreintes.py` — ce que l'écran lit d'une session FINIE (clôture pour `liveness`, récap +
  rapport rendu pour `taches_vue`), calculé une fois par version du fichier et retenu sur
  disque (`clotures_sessions.json`, `recaps_sessions.json`) : un redémarrage ne redécode plus
  le parc (712 sessions, 63 s cache froid, au premier `GET /api/inbox`). `ecrire_tout()` en fin
  de calcul d'écran
- `parc.py` — poids du parc et récupération d'espace EN DEUX TEMPS : `inventory()` (ne touche
  rien), `reclaim()` (range vers `_trash`, réversible), `empty_trash()` (vide pour de bon,
  daté). Les deux derniers sont en simulation sans `confirm=True`. Mesuré : 1,8 Go de parc,
  dont 1,55 Go déjà dans la corbeille
- `listing_cache.py` — `cached_list_sessions()` : TTL 5 s + single-flight devant
  `store.list_sessions()`, servi à `GET /api/sessions` (une rafale ne paie qu'un calcul)
- `analysis.py` — `turn_table()` : par appel LLM durée/tokens/cache/coût ;
  `turn_detail()` : payload annoté cached/new-cache/fresh + réponse rendue.
  Réutilise `web.context_viewer` (v1) et les dumps `debug_payloads/<session>/turns.jsonl`
