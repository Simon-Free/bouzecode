"""Couche de persistance SQLite des tickets (extraite de tickets.py).

Un ticket = ligne (slug, id, data-JSON) dans une DB SQLite en mode WAL (atomicité
et concurrence multi-process). Aucune logique métier ici : uniquement connect,
migration lazy du legacy JSON, upsert, load/save/mutate atomiques.
Ré-exporté par tickets.py (façade)."""
from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from . import _store_connection

# Verrou d'ÉCRITURE intra-process. Il ne couvre PLUS les lectures : en WAL un lecteur obtient
# un snapshot cohérent sans bloquer ni être bloqué, donc sérialiser les lectures reprenait d'une
# main ce que WAL donne de l'autre (une lecture de ticket attendait derrière CHAQUE écriture, y
# compris le tick wake qui écrit sur tous les slugs : ~270 ms d'attente pure mesurés).
# Il reste sur les écritures pour une raison précise : une read-modify-write (`_mutate`) ouvre
# une transaction DIFFÉRÉE — le SELECT prend un snapshot, l'UPDATE tente de le promouvoir en
# écriture, et SQLite refuse IMMÉDIATEMENT (SQLITE_BUSY_SNAPSHOT, que `busy_timeout` ne rejoue
# PAS) si un autre writer a commité entre-temps. Sérialiser les writers du process supprime ce
# cas ; les autres process restent arbitrés par le verrou d'écriture de SQLite + `busy_timeout`.
_tickets_lock = threading.Lock()

TICKETS_DIR = Path.home() / ".bouzecode" / "web_v2" / "tickets"

_log = logging.getLogger(__name__)
_migrated: set[str] = set()  # slugs déjà importés du legacy JSON (garde mémoire, évite un COUNT/op)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _db_path() -> Path:
    # Dérivé de TICKETS_DIR à CHAQUE appel (les tests monkeypatchent TICKETS_DIR).
    return TICKETS_DIR / "tickets.db"


def _connect():
    """Bloc de travail sur la connexion de CE thread vers la base courante (WAL, gardée
    ouverte entre les appels : cf. `_store_connection`). Le chemin est re-dérivé à chaque
    appel, donc un `TICKETS_DIR` déplacé (isolation des tests) change bien de base."""
    return _store_connection.transaction(_db_path())


def _ensure_migrated(conn: sqlite3.Connection, slug: str) -> None:
    """Import LAZY du legacy `~/.bouzecode/web_v2/tickets/{slug}.json` (les 21 tickets prod) vers
    la DB, au tout premier accès à ce slug. La liste JSON est récent-en-tête : on insère en ordre
    INVERSE pour que le 1er élément reçoive le plus grand `seq` (ordre d'affichage préservé). Le
    fichier est ensuite renommé `.json.migrated` (trace, jamais ré-importé)."""
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
                for ticket in reversed(data):  # dernier d'abord → le 1er obtient le plus grand seq
                    if isinstance(ticket, dict) and ticket.get("id"):
                        _upsert_one(conn, slug, ticket)
                _log.info("tickets[%s]: %d tickets migrés du JSON legacy -> SQLite", slug, len(data))
            with contextlib.suppress(OSError):
                legacy.replace(legacy.with_suffix(".json.migrated"))
    _migrated.add(slug)


def _upsert_one(conn: sqlite3.Connection, slug: str, ticket: dict) -> None:
    """Écrit UN ticket (insert ou update sur (slug,id)). ON CONFLICT DO UPDATE préserve la ligne
    existante (donc son `seq` → l'ordre reste stable). Écrire un ticket ne touche QUE sa ligne,
    jamais celles des autres (contrairement au rewrite de la liste JSON complète où deux writers
    concurrents s'écrasaient).

    PORTÉE EXACTE : la granularité par ligne supprime le lost-update ENTRE tickets, pas celui
    d'un MÊME ticket — le `data` passé écrase tout l'ancien. La protection complète, c'est
    `_mutate`, qui relit la ligne et la réécrit dans la MÊME transaction. Écrire un objet
    ticket lu il y a longtemps (`_save`, `update_ticket`) reste une perte possible."""
    conn.execute(
        "INSERT INTO tickets(slug, id, data) VALUES(?, ?, ?) "
        "ON CONFLICT(slug, id) DO UPDATE SET data=excluded.data",
        (slug, ticket["id"], json.dumps(ticket, ensure_ascii=False)),
    )


def _load(slug: str) -> list[dict]:
    """TOUS les tickets d'un slug, récent en tête. Lecture pure, sans verrou de process
    (cf. le commentaire de `_tickets_lock`). Pour UN ticket connu, utiliser `_load_one` :
    décoder toute la liste pour n'en garder qu'un coûte ~95 % de travail jeté."""
    with _connect() as conn:
        _ensure_migrated(conn, slug)
        rows = conn.execute(
            "SELECT data FROM tickets WHERE slug=? ORDER BY seq DESC", (slug,)
        ).fetchall()
    return [json.loads(r[0]) for r in rows]


def _load_one(slug: str, ticket_id: str) -> dict | None:
    """UN ticket, lu par sa clé — l'index UNIQUE(slug, id) ne rend qu'UNE ligne. None si absent.

    C'est le chemin de la page ticket : la version précédente SELECTait toutes les lignes du
    slug et les décodait pour n'en garder qu'une (22 tickets = 6,9 Mo de JSON pour ~5 Ko utiles
    → 572 ms de médiane sur GET /api/tickets/<slug>/<id>)."""
    with _connect() as conn:
        _ensure_migrated(conn, slug)
        row = conn.execute(
            "SELECT data FROM tickets WHERE slug=? AND id=?", (slug, ticket_id)
        ).fetchone()
    return json.loads(row[0]) if row else None


def parent_agent_ids(slug: str) -> set[str]:
    """Les `agent_id` qui sont le PARENT d'au moins un ticket du projet (archivés compris).

    Répond à « ce manager a-t-il réellement dispatché un enfant ? » sans charger un seul
    ticket enfant : SELECT DISTINCT sur la seule colonne utile, aucun décodage JSON en
    Python. Mesuré sur le store réel : 0,1 à 48 ms par projet selon la taille des tickets,
    contre 200 ms+ pour décoder la liste complète. Les archivés SONT comptés : un enfant
    archivé a bel et bien été dispatché, le parent l'attend toujours."""
    with _connect() as conn:
        _ensure_migrated(conn, slug)
        rows = conn.execute(
            "SELECT DISTINCT json_extract(data, '$.parent') FROM tickets WHERE slug=?",
            (slug,),
        ).fetchall()
    return {row[0] for row in rows if row[0]}


def _save_unlocked(slug: str, tickets: list[dict]) -> None:
    """Persiste une LISTE de tickets par UPSERT ticket-par-ticket (pas de delete-all). Aucun
    chemin ne retire un ticket du store (archive = flag `archived`, jamais un retrait), donc un
    upsert ciblé suffit : aucun ticket ABSENT de la liste ne peut être perdu.

    ⚠️ Ce que ce chemin ne protège PAS : les tickets PRÉSENTS dans la liste. Chaque objet
    passé écrase INTÉGRALEMENT sa ligne. Passer un instantané chargé avant les modifications
    d'un tiers, c'est le lost-update silencieux du 2026-07-27 (`refresh_verdicts` réécrivait
    tout le board et effaçait les mutations concurrentes). Pour modifier UN champ d'UN ticket,
    passer par `_mutate` : il relit la version fraîche en base dans la même transaction.
    Ne reste utilisé que pour SEMER un store (fixtures de test, migration)."""
    with _connect() as conn:
        _ensure_migrated(conn, slug)
        for ticket in tickets:
            if isinstance(ticket, dict) and ticket.get("id"):
                _upsert_one(conn, slug, ticket)


def launching_tickets() -> list[tuple[str, dict]]:
    """Tous les tickets EN COURS DE LANCEMENT (launching=True), TOUS projets confondus,
    récent en tête. Renvoie [(slug, ticket)] — le slug vient de la colonne `slug`.

    Sert à l'arbre live (fleet) pour montrer un ticket dès sa création, avant que son
    worktree+venv+spawn (plusieurs secondes) n'ait produit un agent visible.

    Lisait avant un JSON par projet (`TICKETS_DIR.glob("*.json")`) : depuis la migration
    SQLite, ces fichiers sont renommés `.json.migrated` et il n'en reste AUCUN — la fonction
    renvoyait donc TOUJOURS [] et l'arbre restait vide plusieurs secondes après chaque
    création. Aucune migration lazy ici, volontairement : un slug legacy jamais rouvert ne
    peut pas avoir un lancement en cours. NE touche AUCUNE session agent (0 I/O disque agent).

    Coût : présélection SQL des lignes qui CONTIENNENT la clé (~30 ms sur 1300 tickets, contre
    ~110 ms pour tout décoder en Python), puis tri en Python sur la vraie valeur du drapeau —
    insensible aux détails de sérialisation JSON (espaces, ordre des clés)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT slug, data FROM tickets WHERE data LIKE ? ORDER BY seq DESC",
            ('%"launching"%',),
        ).fetchall()
    launching: list[tuple[str, dict]] = []
    for slug, data in rows:
        ticket = json.loads(data)
        if ticket.get("launching"):
            launching.append((slug, ticket))
    return launching


def all_tickets() -> list[tuple[str, dict]]:
    """TOUS les tickets de TOUS les projets, ARCHIVÉS COMPRIS, récent en tête.
    Renvoie [(slug, ticket)] — le slug vient de la colonne `slug`, pas d'un nom de fichier.

    C'est l'itération « tout le store » des passes de BOOT (auto_resume, interrupted_report,
    migrations). Elles faisaient toutes `TICKETS_DIR.glob("*.json")` : depuis la migration
    SQLite ces fichiers sont renommés `.json.migrated` et il n'en reste AUCUN, donc les trois
    passes itéraient sur le VIDE et ne faisaient plus rien, en silence (même bug que
    `launching_tickets`). Les archivés SONT rendus : l'appelant décide (auto_resume les
    écarte, `_build_run_to_work_map` en a besoin — un validateur hérité peut appartenir à
    un ticket déjà archivé).

    Aucune migration lazy ici, volontairement (comme `launching_tickets`) : il ne reste aucun
    JSON legacy à importer, et un slug jamais rouvert n'a rien à reprendre. NE touche AUCUNE
    session agent (0 I/O disque agent) — la classification vivant/mort reste à l'appelant.

    Coût : UNE requête, tri par `seq` en SQL, décodage JSON de chaque ligne (inévitable, les
    appelants lisent `runs`/`comments`). Mesuré sur le store réel de 78 tickets : 6 ms. La
    variante « un SELECT par slug » (`list_tickets` en boucle sur les projets) rouvrait une
    connexion et rejouait `_ensure_migrated` par projet, pour le même résultat."""
    with _connect() as conn:
        rows = conn.execute("SELECT slug, data FROM tickets ORDER BY seq DESC").fetchall()
    return [(slug, json.loads(data)) for slug, data in rows]


def _save(slug: str, tickets: list[dict]) -> None:
    with _tickets_lock:
        _save_unlocked(slug, tickets)


def _mutate(slug: str, ticket_id: str, fn) -> dict | None:
    """Read-modify-write ATOMIQUE d'UN SEUL ticket : SELECT sa ligne, applique `fn`, UPDATE sa
    ligne — en une transaction. Contrairement à l'ancien load-liste + save-liste, muter le ticket
    A n'implique plus de réécrire la ligne de B → deux mutations concurrentes de tickets DIFFÉRENTS
    (serveur + agents CLI) ne se perdent plus. Renvoie le ticket frais muté, ou None si introuvable."""
    with _tickets_lock, _connect() as conn:
        _ensure_migrated(conn, slug)
        row = conn.execute(
            "SELECT data FROM tickets WHERE slug=? AND id=?", (slug, ticket_id)
        ).fetchone()
        if row is None:
            return None
        target = json.loads(row[0])
        if fn(target) is not False:  # fn peut renvoyer False pour signaler « rien changé »
            _upsert_one(conn, slug, target)
        return target
