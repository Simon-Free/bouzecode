"""Couche de persistance SQLite des tickets (extraite de tickets.py).

Un ticket = ligne (slug, id, data-JSON, version) ; ses runs vivent dans la table `runs` et son
journal dans `ticket_events` (`fsm/stockage.py`, `fsm/journal.py`), dans la même base WAL. Le
codec d'une ligne (hydratation, écriture conditionnelle à la version) est `_ligne_ticket`.
Aucune logique métier ici : connexion, lectures, ensemencement, read-modify-write.
Ré-exporté par tickets.py (façade)."""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import contextlib
import json
import logging
import sqlite3
import threading
from pathlib import Path

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import _ligne_ticket, _store_connection
from ._ligne_ticket import VersionObsolete  # noqa: F401 — ré-export
from .fsm import etats, journal, stockage

# Verrou d'ÉCRITURE intra-process (les lecteurs WAL ne l'attendent jamais). Entre process, c'est
# la version conditionnelle qui arbitre : un écrivain en retard ne peut plus rien écraser.
_tickets_lock = threading.RLock()

TICKETS_DIR = bouzecode_data_dir() / "web_v2" / "tickets"

_log = logging.getLogger(__name__)
_migrated: set[str] = set()  # slugs déjà importés du legacy JSON (garde mémoire, évite un COUNT/op)
_RELECTURES_MAX = 5


def _now() -> str:
    return maintenant_iso()


def _db_path() -> Path:
    # Dérivé de TICKETS_DIR à CHAQUE appel (les tests monkeypatchent TICKETS_DIR).
    return TICKETS_DIR / "tickets.db"


def _connect():
    """Bloc de travail sur la connexion de CE thread vers la base courante (WAL, gardée
    ouverte entre les appels : cf. `_store_connection`)."""
    return _store_connection.transaction(_db_path())


def _ensure_migrated(conn: sqlite3.Connection, slug: str) -> None:
    """Import LAZY du legacy `~/.bouzecode/web_v2/tickets/{slug}.json` vers la DB, au tout
    premier accès à ce slug (liste récent-en-tête → insérée à l'envers pour garder l'ordre).
    Le fichier est ensuite renommé `.json.migrated` (trace, jamais ré-importé)."""
    if slug in _migrated:
        return
    row = conn.execute("SELECT COUNT(*) FROM tickets WHERE slug=?", (slug,)).fetchone()
    if row and row[0] == 0:
        legacy = TICKETS_DIR / f"{slug}.json"
        if legacy.is_file():
            try:
                data = json.loads(legacy.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = None
            if isinstance(data, list):
                for ticket in reversed(data):
                    if isinstance(ticket, dict) and ticket.get("id"):
                        _upsert_one(conn, slug, ticket)
                _log.info("tickets[%s]: %d tickets migrés du JSON legacy -> SQLite", slug, len(data))
            with contextlib.suppress(OSError):
                legacy.replace(legacy.with_suffix(".json.migrated"))
    _migrated.add(slug)


def _upsert_one(conn: sqlite3.Connection, slug: str, ticket: dict) -> None:
    """Écrit un ticket tel quel (fixtures, migration) : l'objet passé fait foi."""
    _ligne_ticket.ecrire(conn, slug, ticket, semer=True)


def _load(slug: str) -> list[dict]:
    """TOUS les tickets d'un slug, récent en tête, hydratés (runs du slug en une requête)."""
    with _connect() as conn:
        _ensure_migrated(conn, slug)
        lignes = conn.execute("SELECT data, version FROM tickets WHERE slug=? ORDER BY seq DESC",
                              (slug,)).fetchall()
        runs = stockage.runs_par_ticket(conn, slug)
        notes = journal.commentaires_par_ticket(conn, slug)
        return [_ligne_ticket.hydrater(conn, slug, ticket, version, runs.get((slug, ticket["id"]), []),
                                       notes.get((slug, ticket["id"]), []))
                for ticket, version in ((json.loads(d), v) for d, v in lignes)]


def _load_one(slug: str, ticket_id: str) -> dict | None:
    """UN ticket, lu par sa clé (index UNIQUE(slug, id)). None si absent."""
    with _connect() as conn:
        _ensure_migrated(conn, slug)
        return _ligne_ticket.lire(conn, slug, ticket_id)


def parent_agent_ids(slug: str) -> set[str]:
    """Les `agent_id` PARENTS d'au moins un ticket du projet (archivés compris), sans décoder
    un seul ticket : SELECT DISTINCT sur la seule colonne utile."""
    with _connect() as conn:
        _ensure_migrated(conn, slug)
        rows = conn.execute("SELECT DISTINCT json_extract(data, '$.parent') FROM tickets"
                            " WHERE slug=?", (slug,)).fetchall()
    return {row[0] for row in rows if row[0]}


def all_tickets() -> list[tuple[str, dict]]:
    """TOUS les tickets de TOUS les projets, ARCHIVÉS COMPRIS, récent en tête : [(slug, ticket)].
    Itération « tout le store » des passes de boot et des vues globales (deux requêtes)."""
    with _connect() as conn:
        lignes = conn.execute("SELECT slug, data, version FROM tickets ORDER BY seq DESC").fetchall()
        runs = stockage.runs_par_ticket(conn)
        notes = journal.commentaires_par_ticket(conn)
        return [(slug, _ligne_ticket.hydrater(conn, slug, ticket, version,
                                              runs.get((slug, ticket["id"]), []),
                                              notes.get((slug, ticket["id"]), [])))
                for slug, ticket, version in ((s, json.loads(d), v) for s, d, v in lignes)]


def tickets_dans_les_etats(states: tuple[str, ...]) -> list[tuple[str, dict]]:
    """Les tickets (tous projets, archivés compris) dont `state` est l'un de `states`."""
    marques = ",".join("?" * len(states))
    with _connect() as conn:
        lignes = conn.execute(
            f"SELECT slug, data, version FROM tickets WHERE json_extract(data, '$.state') IN"
            f" ({marques}) ORDER BY seq DESC", states).fetchall()
        return [(slug, _ligne_ticket.hydrater(conn, slug, json.loads(data), version))
                for slug, data, version in lignes]


def launching_tickets() -> list[tuple[str, dict]]:
    """Les tickets EN COURS DE LANCEMENT (`state == provisioning`), tous projets, récent en
    tête : l'arbre live les montre dès leur création, avant qu'un agent existe. Un lancement
    figé (serveur tué en plein provisionnement) est clos par le watchdog (`launch_failed`)."""
    return tickets_dans_les_etats((etats.PROVISIONING,))


def _save_unlocked(slug: str, tickets: list[dict]) -> None:
    """SÈME une liste de tickets (fixtures de test, migration). Ne sert jamais à modifier un
    ticket existant : passer par `_mutate`, `update_ticket` ou `ticket_fsm`."""
    with _connect() as conn:
        _ensure_migrated(conn, slug)
        for ticket in tickets:
            if isinstance(ticket, dict) and ticket.get("id"):
                _upsert_one(conn, slug, ticket)


def _save(slug: str, tickets: list[dict]) -> None:
    with _tickets_lock:
        _save_unlocked(slug, tickets)


def _mutate(slug: str, ticket_id: str, fn) -> dict | None:
    """Read-modify-write ATOMIQUE d'UN ticket : relit sa version fraîche, applique `fn`, écrit
    sous condition de version — et REJOUE si un autre process a écrit entre-temps. `fn` peut
    renvoyer False pour « rien changé ». Rend le ticket frais muté, ou None si introuvable."""
    for _essai in range(_RELECTURES_MAX):
        with _tickets_lock, _connect() as conn:
            _ensure_migrated(conn, slug)
            frais = _ligne_ticket.lire(conn, slug, ticket_id)
            if frais is None:
                return None
            if fn(frais) is False:
                return frais
            try:
                _ligne_ticket.ecrire(conn, slug, frais, version_lue=frais["version"])
            except VersionObsolete:
                conn.rollback()
                continue
        _perimer_l_arbre()
        return frais
    raise VersionObsolete(slug, ticket_id, -1, -1, "?")


def _perimer_l_arbre() -> None:
    """Un ticket a changé : la page d'arbre mémorisée est périmée (servie encore une fois,
    recalculée aussitôt), sans attendre le TTL."""
    from . import fleet_cache
    fleet_cache.expire_all()
