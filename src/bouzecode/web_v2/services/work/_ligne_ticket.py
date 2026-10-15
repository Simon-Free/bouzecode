# [desc] Codec d'UNE ligne de ticket : lecture hydratée (runs, journal, version, état), écriture conditionnelle à la version (verrou optimiste). [/desc]
"""Lire et écrire une ligne `tickets(slug, id, data, version)`.

VERROU OPTIMISTE (spec §9) : chaque écriture incrémente `version` et n'aboutit que si la ligne
n'a pas bougé depuis la lecture. Un instantané périmé lève `VersionObsolete` (409
`version_obsolete`) au lieu d'écraser l'écriture d'un autre. `state` et `state_reason` ne sont
jamais changés ici, sauf par la machine à états (`etat=`) ou un ensemencement (`semer=`)."""
from __future__ import annotations

import json

from .fsm import correspondance, etats, journal, stockage

#: Jamais écrits dans le JSON du ticket : portés par leurs propres tables / colonnes.
_HORS_JSON = ("runs", "version")


class VersionObsolete(RuntimeError):
    """Écriture d'un instantané périmé : un autre écrivain a modifié le ticket entre-temps."""

    def __init__(self, slug: str, ticket_id: str, attendue: int, courante: int, state: str):
        super().__init__(f"ticket {slug}/{ticket_id} modifié entre-temps "
                         f"(version {attendue} lue, {courante} en base)")
        self.details = {"ticket_id": ticket_id, "version": courante,
                        "version_lue": attendue, "state": state}


def hydrater(conn, slug: str, ticket: dict, version: int, runs: list | None = None,
             commentaires: list | None = None) -> dict:
    """Le ticket tel que le servent les lectures : runs de la table, commentaires du journal
    ajoutés aux anciens, `version`, et un `state` même pour une ligne pas encore migrée."""
    if runs is None:
        runs = stockage.runs_du_ticket(conn, slug, ticket["id"])
    #  Ligne d'avant le lot L2 pas encore migrée : ses runs sont encore dans son JSON.
    ticket["runs"] = runs or [r for r in ticket.get("runs") or [] if isinstance(r, dict)]
    ticket["version"] = version
    if ticket.get("state") not in etats.ETATS:
        ticket["state"], ticket["state_reason"] = correspondance.etat_initial(ticket)
    if commentaires is None:
        commentaires = journal.commentaires(conn, slug, ticket["id"])
    ticket["comments"] = list(ticket.get("comments") or []) + commentaires
    return ticket


def ligne(conn, slug: str, ticket_id: str):
    return conn.execute("SELECT data, version FROM tickets WHERE slug=? AND id=?",
                        (slug, ticket_id)).fetchone()


def lire(conn, slug: str, ticket_id: str) -> dict | None:
    trouvee = ligne(conn, slug, ticket_id)
    return hydrater(conn, slug, json.loads(trouvee[0]), trouvee[1]) if trouvee else None


def _cle(commentaire: dict) -> tuple:
    return (commentaire.get("at"), commentaire.get("text"))


def _commentaires(conn, slug: str, ticket: dict, ancien: dict | None, semer: bool) -> list:
    """Le champ `comments` du JSON (les anciens seulement). Un commentaire ajouté à l'objet
    par un appelant devient un ÉVÉNEMENT du journal, jamais une ligne du JSON."""
    portes = [c for c in ticket.get("comments") or [] if isinstance(c, dict)]
    if ancien is None:
        return portes
    au_journal = {_cle(c) for c in journal.commentaires(conn, slug, ticket["id"])}
    if semer:
        return [c for c in portes if _cle(c) not in au_journal]
    anciens = [c for c in ancien.get("comments") or [] if isinstance(c, dict)]
    connus = au_journal | {_cle(c) for c in anciens}
    for nouveau in (c for c in portes if _cle(c) not in connus):
        journal.ecrire(conn, slug, ticket["id"], journal.COMMENT, "",
                       {"text": nouveau.get("text", ""), "sent": bool(nouveau.get("sent"))},
                       at=str(nouveau.get("at") or ""))
    return anciens


def _etat_ecrit(ticket: dict, ancien: dict | None, etat, semer: bool) -> tuple:
    if etat is not None:
        return etat
    if ancien is not None and not semer and ancien.get("state") in etats.ETATS:
        return ancien["state"], ancien.get("state_reason")
    if ticket.get("state") in etats.ETATS:
        return ticket["state"], ticket.get("state_reason")
    return correspondance.etat_initial(ticket)


def ecrire(conn, slug: str, ticket: dict, version_lue: int | None = None,
           etat: tuple | None = None, semer: bool = False) -> int:
    """Écrit UNE ligne. `version_lue` : refus (`VersionObsolete`) si la base a bougé depuis.
    `etat` : réservé à `ticket_fsm`. `semer` : fixtures et migration, l'objet passé fait foi.
    Rend la nouvelle version (aussi reportée dans `ticket["version"]` et `ticket["state"]`)."""
    trouvee = ligne(conn, slug, ticket["id"])
    ancien = json.loads(trouvee[0]) if trouvee else None
    courante = trouvee[1] if trouvee else 0
    if version_lue is not None and trouvee and courante != version_lue:
        raise VersionObsolete(slug, ticket["id"], version_lue, courante,
                              str((ancien or {}).get("state")))
    data = {k: v for k, v in ticket.items() if k not in _HORS_JSON}
    data["comments"] = _commentaires(conn, slug, ticket, ancien, semer)
    data["state"], data["state_reason"] = _etat_ecrit(ticket, ancien, etat, semer)
    texte = json.dumps(data, ensure_ascii=False)
    if trouvee is None:
        conn.execute("INSERT INTO tickets(slug, id, data, version) VALUES(?, ?, ?, 1)",
                     (slug, ticket["id"], texte))
    elif conn.execute("UPDATE tickets SET data=?, version=version+1 WHERE slug=? AND id=? AND"
                      " version=?", (texte, slug, ticket["id"], courante)).rowcount != 1:
        raise VersionObsolete(slug, ticket["id"], courante, courante + 1,
                              str((ancien or {}).get("state")))
    stockage.synchroniser(conn, slug, ticket["id"], ticket.get("runs") or [])
    ticket["version"] = courante + 1
    ticket["state"], ticket["state_reason"] = data["state"], data["state_reason"]
    return courante + 1
