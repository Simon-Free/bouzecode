# [desc] Journal append-only des tickets (`ticket_events`) : chaque transition, chaque commentaire, chaque demande d'arrêt ; lecture `events(slug, ticket_id, since)`. [/desc]
"""Le journal d'un ticket (spec §3.3) : une ligne par événement, jamais réécrite.

Il remplace les commentaires automatiques posés sur le ticket, sert à l'audit et au réveil des
managers (`events(..., since=seq)`). Chaque transition de `ticket_fsm` y écrit son événement
DANS la transaction qui change l'état : un état sans son événement est impossible."""
from __future__ import annotations

import json
import sqlite3

from bouzecode.web_v2.services.horodatage import maintenant_iso

#: Événement d'un commentaire (humain ou agent) : `{text, sent}`.
COMMENT = "comment"
#: Changement de `state_reason` sans changement d'état (`ticket_fsm.motiver`).
MOTIF = "state_reason"
#: Demande d'arrêt posée / levée (remplace le drapeau `arret_demande`).
ARRET_DEMANDE, ARRET_LEVE = "arret_demande", "arret_leve"


def _maintenant() -> str:
    return maintenant_iso()


def ecrire(conn: sqlite3.Connection, slug: str, ticket_id: str, kind: str,
           actor: str = "", data: dict | None = None, at: str = "") -> int:
    """Ajoute un événement ; rend son `seq` (croissant sur tout le store)."""
    curseur = conn.execute(
        "INSERT INTO ticket_events(slug, ticket_id, at, kind, actor, data) VALUES(?,?,?,?,?,?)",
        (slug, ticket_id, at or _maintenant(), kind, actor or "",
         json.dumps(data or {}, ensure_ascii=False)))
    return int(curseur.lastrowid)


def _en_dict(ligne) -> dict:
    seq, ticket_id, at, kind, actor, data = ligne
    return {"seq": seq, "ticket_id": ticket_id, "at": at, "kind": kind, "actor": actor,
            "data": json.loads(data or "{}")}


def lire(conn: sqlite3.Connection, slug: str, ticket_id: str, since: int = 0,
         kinds: tuple[str, ...] = ()) -> list[dict]:
    """Les événements d'un ticket de `seq` > `since`, dans l'ordre (filtrés par `kinds`)."""
    requete = ("SELECT seq, ticket_id, at, kind, actor, data FROM ticket_events"
               " WHERE slug=? AND ticket_id=? AND seq>?")
    valeurs: list = [slug, ticket_id, int(since or 0)]
    if kinds:
        requete += f" AND kind IN ({','.join('?' * len(kinds))})"
        valeurs += list(kinds)
    return [_en_dict(ligne) for ligne in conn.execute(requete + " ORDER BY seq", valeurs)]


def dernier(conn: sqlite3.Connection, slug: str, ticket_id: str,
            kinds: tuple[str, ...]) -> dict | None:
    """Le plus récent des événements de ces kinds, ou None."""
    ligne = conn.execute(
        "SELECT seq, ticket_id, at, kind, actor, data FROM ticket_events WHERE slug=? AND"
        f" ticket_id=? AND kind IN ({','.join('?' * len(kinds))}) ORDER BY seq DESC LIMIT 1",
        [slug, ticket_id, *kinds]).fetchone()
    return _en_dict(ligne) if ligne else None


def commentaires(conn: sqlite3.Connection, slug: str, ticket_id: str) -> list[dict]:
    """Les commentaires au format historique `{at, text, sent}` (récent en dernier)."""
    return [{"at": e["at"], "text": e["data"].get("text", ""), "sent": bool(e["data"].get("sent"))}
            for e in lire(conn, slug, ticket_id, kinds=(COMMENT,))]


def commentaires_par_ticket(conn: sqlite3.Connection, slug: str | None = None) -> dict[tuple, list]:
    """{(slug, ticket_id): commentaires} d'un projet (ou de tout le store) en UNE requête."""
    requete = "SELECT slug, ticket_id, at, data FROM ticket_events WHERE kind=?"
    valeurs: list = [COMMENT]
    if slug is not None:
        requete += " AND slug=?"
        valeurs.append(slug)
    index: dict[tuple, list] = {}
    for s, ticket_id, at, data in conn.execute(requete + " ORDER BY seq", valeurs):
        contenu = json.loads(data or "{}")
        index.setdefault((s, ticket_id), []).append(
            {"at": at, "text": contenu.get("text", ""), "sent": bool(contenu.get("sent"))})
    return index
