# [desc] Tables `runs` et `ticket_events` + colonne `version` des tickets, dans la base tickets.db : schéma, lecture des runs, écriture d'un run. [/desc]
"""Les runs ne vivent plus dans le JSON du ticket : une ligne par run dans `runs` (spec §3.2).

Avant, chaque battement d'un run réécrivait le ticket entier, et `update_ticket` devait
« réintégrer » les runs ajoutés entre-temps par un autre écrivain. Désormais :
  * un ticket lu porte `runs` HYDRATÉS depuis la table (récent en tête, comme avant) ;
  * l'écriture d'un ticket synchronise ses runs par `agent_id` sans jamais en supprimer ;
  * `state`, `end` et `ended_at` d'un run ne sont écrits que par la machine à états ;
  * les champs transitoires (`key`, `pid_alive`) ne sont jamais persistés (C3).
Les champs propres à un kind (run `remote` : execution_id, url… ; `completed`, `dead_ticks`…)
voyagent dans la colonne JSON `extra`."""
from __future__ import annotations

import json
import sqlite3

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS runs ("
    " agent_id TEXT PRIMARY KEY, slug TEXT NOT NULL, ticket_id TEXT NOT NULL,"
    " seq INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'work',"
    " state TEXT NOT NULL DEFAULT 'running', \"end\" TEXT, started_at TEXT, ended_at TEXT,"
    " turns INTEGER NOT NULL DEFAULT 0, model TEXT NOT NULL DEFAULT '',"
    " profile TEXT NOT NULL DEFAULT '', extra TEXT NOT NULL DEFAULT '{}')",
    "CREATE INDEX IF NOT EXISTS runs_par_ticket ON runs(slug, ticket_id, seq)",
    "CREATE TABLE IF NOT EXISTS ticket_events ("
    " seq INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, ticket_id TEXT NOT NULL,"
    " at TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL DEFAULT '',"
    " data TEXT NOT NULL DEFAULT '{}')",
    "CREATE INDEX IF NOT EXISTS events_par_ticket ON ticket_events(slug, ticket_id, seq)",
    #  `Idempotency-Key` d'une création de ticket (spec §9) : rejouer la clé rend le même ticket.
    "CREATE TABLE IF NOT EXISTS idempotence ("
    " cle TEXT PRIMARY KEY, slug TEXT NOT NULL, ticket_id TEXT NOT NULL, at TEXT NOT NULL)",
)

#: Colonnes « simples » d'un run (le reste va dans `extra`).
_COLONNES = ("kind", "started_at", "turns", "model", "profile")
#: Écrits par la seule machine à états (`ecrire_etat`), jamais par une synchronisation.
_PAR_LA_FSM = ("state", "end", "ended_at")
#: Jamais persistés : attachés à la lecture par un appelant (C3).
TRANSITOIRES = ("key", "pid_alive", "live_state")
_HORS_EXTRA = ("agent_id", "seq", *_COLONNES, *_PAR_LA_FSM, *TRANSITOIRES)


class RunDejaRattache(ValueError):
    """Un `agent_id` est la clé d'un run : il ne peut pas appartenir à deux tickets."""


def assurer_le_schema(conn: sqlite3.Connection) -> None:
    """Crée `runs` / `ticket_events` et la colonne `tickets.version` (idempotent)."""
    for instruction in SCHEMA:
        conn.execute(instruction)
    colonnes = {ligne[1] for ligne in conn.execute("PRAGMA table_info(tickets)")}
    if "version" not in colonnes:
        conn.execute("ALTER TABLE tickets ADD COLUMN version INTEGER NOT NULL DEFAULT 0")


_SELECT = ("SELECT agent_id, slug, ticket_id, seq, kind, state, \"end\", started_at, ended_at,"
           " turns, model, profile, extra FROM runs")


def _en_dict(ligne) -> dict:
    agent_id, _slug, _tid, seq, kind, state, end, started_at, ended_at, turns, model, profile, extra = ligne
    run = {**json.loads(extra or "{}"), "agent_id": agent_id, "seq": seq, "kind": kind,
           "state": state, "started_at": started_at or "", "turns": turns, "model": model or ""}
    if profile:
        run["profile"] = profile
    if end:
        run["end"] = json.loads(end)
    if ended_at:
        run["ended_at"] = ended_at
    return run


def runs_du_ticket(conn: sqlite3.Connection, slug: str, ticket_id: str) -> list[dict]:
    """Les runs d'un ticket, le plus récent en tête."""
    lignes = conn.execute(_SELECT + " WHERE slug=? AND ticket_id=? ORDER BY seq DESC",
                          (slug, ticket_id)).fetchall()
    return [_en_dict(ligne) for ligne in lignes]


def runs_par_ticket(conn: sqlite3.Connection, slug: str | None = None) -> dict[tuple, list[dict]]:
    """{(slug, ticket_id): runs} pour un projet (ou tout le store) en UNE requête."""
    if slug is None:
        lignes = conn.execute(_SELECT + " ORDER BY seq DESC").fetchall()
    else:
        lignes = conn.execute(_SELECT + " WHERE slug=? ORDER BY seq DESC", (slug,)).fetchall()
    index: dict[tuple, list[dict]] = {}
    for ligne in lignes:
        index.setdefault((ligne[1], ligne[2]), []).append(_en_dict(ligne))
    return index


def _extra(run: dict) -> str:
    return json.dumps({k: v for k, v in run.items() if k not in _HORS_EXTRA}, ensure_ascii=False)


def _proprietaire(conn, agent_id: str):
    return conn.execute("SELECT slug, ticket_id FROM runs WHERE agent_id=?", (agent_id,)).fetchone()


def inserer(conn: sqlite3.Connection, slug: str, ticket_id: str, run: dict) -> dict:
    """Ajoute un run en tête du ticket (seq = max + 1). Rend le run tel qu'écrit."""
    proprio = _proprietaire(conn, run["agent_id"])
    if proprio is not None and tuple(proprio) != (slug, ticket_id):
        raise RunDejaRattache(f"le run {run['agent_id']} appartient déjà au ticket "
                              f"{proprio[0]}/{proprio[1]}")
    if proprio is not None:
        synchroniser(conn, slug, ticket_id, [run])
        return run
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM runs WHERE slug=? AND ticket_id=?",
                       (slug, ticket_id)).fetchone()[0]
    end = run.get("end")
    conn.execute(
        "INSERT INTO runs(agent_id, slug, ticket_id, seq, kind, state, \"end\", started_at,"
        " ended_at, turns, model, profile, extra) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run["agent_id"], slug, ticket_id, run.get("seq") or seq, str(run.get("kind") or "work"),
         str(run.get("state") or "running"), json.dumps(end, ensure_ascii=False) if end else None,
         run.get("started_at") or "", run.get("ended_at") or None, int(run.get("turns") or 0),
         str(run.get("model") or ""), str(run.get("profile") or ""), _extra(run)))
    run["seq"] = run.get("seq") or seq
    return run


def synchroniser(conn: sqlite3.Connection, slug: str, ticket_id: str, runs: list) -> None:
    """Écrit les champs ordinaires des runs portés par un ticket qu'on enregistre. Un run inconnu
    est inséré ; aucun run n'est jamais supprimé ; `state`/`end` restent ceux de la FSM.
    La liste est récente EN TÊTE : on la parcourt à rebours pour que l'ordre (`seq`) des runs
    insérés soit celui de la liste."""
    for run in reversed(runs or []):
        if not (isinstance(run, dict) and run.get("agent_id")):
            continue
        proprio = _proprietaire(conn, run["agent_id"])
        if proprio is None:
            inserer(conn, slug, ticket_id, dict(run))
            continue
        if tuple(proprio) != (slug, ticket_id):
            raise RunDejaRattache(f"le run {run['agent_id']} appartient déjà au ticket "
                                  f"{proprio[0]}/{proprio[1]}")
        conn.execute(
            "UPDATE runs SET kind=?, started_at=?, turns=?, model=?, profile=?, extra=?"
            " WHERE agent_id=? AND slug=? AND ticket_id=?",
            (str(run.get("kind") or "work"), run.get("started_at") or "",
             int(run.get("turns") or 0), str(run.get("model") or ""),
             str(run.get("profile") or ""), _extra(run), run["agent_id"], slug, ticket_id))


def ecrire_etat(conn: sqlite3.Connection, agent_id: str, state: str,
                end: dict | None = None, ended_at: str | None = None) -> None:
    """Réservé à `ticket_fsm` : l'état d'un run suit celui de son ticket."""
    conn.execute("UPDATE runs SET state=?, \"end\"=COALESCE(?, \"end\"), ended_at=? WHERE agent_id=?",
                 (state, json.dumps(end, ensure_ascii=False) if end else None, ended_at, agent_id))
