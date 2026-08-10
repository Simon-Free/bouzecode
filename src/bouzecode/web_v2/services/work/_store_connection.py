"""Connexion SQLite du store de tickets : UNE par thread et par base, gardée ouverte.

Ouvrir une connexion coûte 30 à 130 ms sur le store réel (ouverture du `.db`, de son
`-wal` de 4 Mo, et `PRAGMA journal_mode=WAL` qui réclame un verrou exclusif pendant que
N agents écrivent), contre 0,03 ms sur une connexion déjà ouverte.
`GET /api/projects/<slug>/tickets` en ouvrait ~101 par requête — une par `_load`, une par
`get_ticket` de `workflow.advance`, une par `update_ticket` de `wake._stamp_liveness` —
soit ~13 s des ~25 s de la requête, en PURE ouverture. Aucune de ces briques n'avait
besoin d'une connexion NEUVE : elles avaient besoin d'UNE connexion.

THREAD-LOCAL, jamais partagée : sqlite3 refuse par défaut qu'une connexion voyage entre
threads, et une connexion par thread évite d'ajouter un verrou applicatif entre requêtes
Flask. Clé sur le CHEMIN de la base, pour que les tests — qui déplacent `TICKETS_DIR` à
chaque test — n'héritent JAMAIS de la connexion du store précédent.

LA FRAÎCHEUR EST INTACTE, et ce n'est pas un compromis : hors transaction, une connexion
WAL relit l'état COMMITÉ le plus récent à CHAQUE instruction, y compris celui écrit par un
autre thread ou un autre process (agents CLI). Rien n'est mémorisé ici — ni ticket, ni
statut, ni instantané : seul le descripteur de fichier est réutilisé. Figer un instantané
demanderait une transaction ouverte, or chaque bloc se termine par `commit` (succès) ou
`rollback` (échec) : aucune ne survit à son bloc.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path

_local = threading.local()

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS tickets ("
    "  seq  INTEGER PRIMARY KEY AUTOINCREMENT,"  # ordre de création (récent = plus grand)
    "  slug TEXT NOT NULL,"
    "  id   TEXT NOT NULL,"
    "  data TEXT NOT NULL,"                       # le ticket complet en JSON
    "  UNIQUE(slug, id))"
)


def connection(db_path: Path) -> sqlite3.Connection:
    """La connexion de CE thread vers `db_path`, ouverte à la première demande.

    Mode WAL : atomicité, durabilité et concurrence MULTI-PROCESS natives. C'est le fix de
    fond du WinError5 — avant, un gros JSON monolithique était réécrit EN ENTIER par le
    serveur ET N agents CLI sans arbitre commun (os.replace = MoveFileEx échouait
    ACCESS_DENIED sous lecture concurrente). WAL : lecteurs non bloquants, écritures
    sérialisées par le verrou DB de SQLite, `busy_timeout` absorbe les collisions
    inter-process. Le mode est PERSISTANT (inscrit dans l'en-tête du fichier) : le poser à
    l'ouverture de la connexion suffit — le rejouer à chaque requête ne servait à rien et
    coûtait le verrou exclusif."""
    cached = getattr(_local, "connection", None)
    if cached is not None:
        if _local.db_path == str(db_path):
            return cached
        cached.close()  # la base a changé (isolation des tests) : celle-ci ne vaut plus rien
        _local.connection = None
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(SCHEMA)
    conn.commit()
    _local.connection, _local.db_path = conn, str(db_path)
    return conn


@contextlib.contextmanager
def transaction(db_path: Path):
    """Bloc de travail sur la connexion de ce thread : commit à la sortie normale, rollback
    si l'appelant lève. Le rollback n'est PAS un try/except décoratif : la connexion SURVIT
    au bloc, donc une transaction laissée ouverte par une mutation en échec serait héritée —
    puis commitée — par le bloc suivant. L'erreur, elle, remonte intacte."""
    conn = connection(db_path)
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
