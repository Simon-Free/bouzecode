# fsm/

## Purpose
La machine à états des tickets (spec ticketing §3, §4, lot L2) : un seul état persisté par
ticket, écrit par `../ticket_fsm.py` seul ; ses runs et son journal dans `tickets.db`.

## Usage
- `etats.py` — les 12 états, les événements, `TRANSITIONS` (la table §4), `cible()`.
- `stockage.py` — tables `runs` (agent_id PK, slug, ticket_id, seq, kind, state, end, started_at,
  ended_at, turns, model, profile, extra) et `ticket_events`, colonne `tickets.version` ;
  `runs_du_ticket`, `runs_par_ticket`, `inserer`, `synchroniser`, `ecrire_etat` (FSM seule).
- `journal.py` — `ecrire`, `lire(since)`, `dernier`, `commentaires` (événements `comment`).
- `cycle_des_runs.py` — l'état d'un run suit la transition de son ticket (un seul run ouvert).
- `correspondance.py` — anciens drapeaux → `state` + `state_reason` (table documentée).
- `migration.py` — `migrer(conn, affiner)` : runs du JSON → table, drapeaux → état, `legacy`.
