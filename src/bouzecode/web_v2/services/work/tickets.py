# [desc] Façade métier ticket : CRUD, runs (table `runs`), commentaires (journal), ré-exportant _persistence (SQLite) et le rapport final. L'état ne s'écrit que par ticket_fsm. [/desc]
"""Un ticket = {id, title, prompt, created_at, state, state_reason, version, runs[], comments[]}.

`state` est l'unique état persisté (spec ticketing §4) : il ne change que par
`ticket_fsm.appliquer`. Les runs vivent dans la table `runs` (hydratés à la lecture, le plus
récent en tête), les commentaires sont des événements du journal (les anciens restent lus).
Run = {agent_id, kind: work|merge_fix|remote, state, end, model, started_at, turns…}.

Façade : la couche SQLite vit dans `_persistence.py` / `_ligne_ticket.py`, l'extraction du
rapport final dans `_final_answer.py` ; ré-exportées pour que les appelants gardent
`tickets.<symbole>`."""
from __future__ import annotations

import uuid

from . import ticket_fsm
from ._final_answer import extract_final_answer  # noqa: F401 — ré-export façade
from ._persistence import (  # noqa: F401 — ré-export façade
    TICKETS_DIR,
    VersionObsolete,
    _connect,
    _db_path,
    _ensure_migrated,
    _load,
    _load_one,
    _mutate,
    _now,
    _perimer_l_arbre,
    _save,
    _save_unlocked,
    _tickets_lock,
    _upsert_one,
    all_tickets,
    launching_tickets,
    parent_agent_ids,
    tickets_dans_les_etats,
)
from ._status import derive_status  # noqa: F401 — ré-export façade
from .etat_ticket import vue as vue_etat
from .fsm import etats, journal
from .runs_ticket import (  # noqa: F401 — ré-export façade
    add_run,
    mark_run_completed,
    refresh_run_states,
    set_launching,
)


def create_ticket(slug: str, title: str, prompt: str) -> dict:
    """Crée le ticket en `created` (version 1) et journalise sa création."""
    ticket = {
        "id": uuid.uuid4().hex[:8], "title": title.strip(), "prompt": prompt.strip(),
        "created_at": _now(), "state": etats.CREATED, "state_reason": None, "comments": [],
    }
    with _tickets_lock, _connect() as conn:  # INSERT d'une ligne : seq auto → apparaît en tête
        _ensure_migrated(conn, slug)
        _upsert_one(conn, slug, ticket)
        journal.ecrire(conn, slug, ticket["id"], "created", "serveur", {"vers": etats.CREATED})
    ticket["runs"] = []
    return ticket


def get_ticket(slug: str, ticket_id: str) -> dict | None:
    """LE ticket demandé (archivé compris), ou None s'il n'existe pas. Lit UNE ligne."""
    return _load_one(slug, ticket_id)


def archive_ticket(slug: str, ticket_id: str, par: str = "") -> dict | None:
    """Archivage RÉVERSIBLE : `archived_at` est un attribut ORTHOGONAL à l'état (spec §3.1),
    jamais un état. `par` trace l'origine d'un archivage automatique (ex. « tache:<id> »)."""
    champs = {"archived": True, "archived_at": _now()}
    if par:
        champs["archived_by"] = par
    ticket = _mutate(slug, ticket_id, lambda t: t.update(champs))
    if ticket is not None:
        ticket_fsm.noter(slug, ticket_id, "archived", par or "serveur")
    return ticket


def unarchive_ticket(slug: str, ticket_id: str) -> dict | None:
    """Annule l'archivage : le ticket revient sur le board actif. None si inconnu."""
    def _apply(t: dict) -> None:
        for champ in ("archived", "archived_at", "archived_by"):
            t.pop(champ, None)
    ticket = _mutate(slug, ticket_id, _apply)
    if ticket is not None:
        ticket_fsm.noter(slug, ticket_id, "unarchived")
    return ticket


def statut_lisible(status: str) -> dict:
    """Un mot historique de statut dans le lexique UNIQUE de l'écran (`status_ui`, libellé)."""
    from .lexique import libelle_ticket, statut_ticket
    return {"status_ui": statut_ticket(status), "libelle_statut": libelle_ticket(status)}


def ticket_summary(ticket: dict) -> dict:
    """Forme légère : sans prompt ni texte de commentaire ; l'état est celui du ticket."""
    runs_light = [{k: v for k, v in r.items()
                   if k in ("agent_id", "kind", "model", "state", "end", "question")}
                  for r in ticket.get("runs") or [] if isinstance(r, dict)]
    summary = {
        "id": ticket["id"], "title": ticket["title"], **vue_etat(ticket),
        "created_at": ticket["created_at"],
        "comments_count": len(ticket.get("comments") or []), "runs": runs_light,
    }
    for cle in ("typology", "isolation", "parent"):
        if cle in ticket:
            summary[cle] = ticket[cle]
    if ticket.get("ephemeral"):
        summary["ephemeral"] = True
    if ticket.get("archived"):
        summary["archived"] = True
    return summary


def update_ticket(slug: str, ticket: dict) -> None:
    """Réécrit les champs ordinaires du ticket, SOUS CONDITION DE VERSION : un instantané lu
    avant l'écriture d'un autre lève `VersionObsolete` au lieu de l'écraser. Les runs sont
    synchronisés par `agent_id` (jamais supprimés) ; `state` n'est jamais touché ici."""
    if not ticket.get("id"):
        return
    from . import _ligne_ticket
    with _tickets_lock, _connect() as conn:
        _ensure_migrated(conn, slug)
        _ligne_ticket.ecrire(conn, slug, ticket, version_lue=ticket.get("version"))
    _perimer_l_arbre()


def poser(slug: str, ticket: dict, **champs) -> dict | None:
    """Écrit des champs ORDINAIRES sur la version fraîche du ticket (read-modify-write, jamais un
    instantané) et les reflète sur l'objet appelant, version comprise. `None` retire le champ."""
    def _apply(frais: dict) -> None:
        for cle, valeur in champs.items():
            if valeur is None:
                frais.pop(cle, None)
            else:
                frais[cle] = valeur
    frais = _mutate(slug, ticket["id"], _apply)
    _apply(ticket)
    if frais is not None:
        ticket["version"], ticket["state"] = frais["version"], frais["state"]
        ticket["state_reason"] = frais.get("state_reason")
    return frais


def add_comment(slug: str, ticket: dict, text: str, sent: bool) -> None:
    """Un commentaire est un ÉVÉNEMENT du journal (`comment`), plus une ligne du JSON."""
    comment = {"at": _now(), "text": text, "sent": sent}
    ticket_fsm.noter(slug, ticket["id"], journal.COMMENT, "serveur", at=comment["at"],
                     text=text, sent=sent)
    ticket.setdefault("comments", []).append(comment)


def list_tickets(slug: str, refresh: bool = False, done_agent: str = "",
                 persist: bool = True, include_archived: bool = False,
                 agents_index: dict | None = None) -> list[dict]:
    """Les tickets d'un projet (archivés masqués par défaut). `refresh` attache en plus, EN
    MÉMOIRE, la vivacité constatée de chaque run (`live_state`) — jamais persistée, jamais
    un état : l'état est `ticket.state`."""
    tickets = [t for t in _load(slug) if include_archived or not t.get("archived")]
    if refresh:
        refresh_run_states(slug, tickets, done_agent, agents_index=agents_index)
    return tickets
