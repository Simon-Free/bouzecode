"""Plusieurs threads ouvrent en même temps une base de tickets NEUVE.

Passer une base neuve en WAL exige un verrou exclusif, et SQLite répond alors « database is
locked » SANS attendre le `busy_timeout` si un autre thread tient la base au même instant.
Vu sous -n 8 sur tests/test_overview_perf.py : `projects.overview` interroge trois projets
depuis trois threads, qui ouvraient chacun leur connexion. Sans le verrou d'ouverture, 44
essais sur 200 échouaient avec quatre threads.
"""
import threading

from bouzecode.web_v2.services.work import _store_connection


def _ouvrir_ensemble(db, n: int = 4) -> list[str]:
    depart = threading.Barrier(n, timeout=10)
    erreurs: list[str] = []

    def ouvrir():
        depart.wait()
        try:
            with _store_connection.transaction(db) as conn:
                conn.execute("SELECT count(*) FROM tickets").fetchone()
        except Exception as exc:  # noqa: BLE001 — c'est précisément ce qu'on compte
            erreurs.append(repr(exc))
    fils = [threading.Thread(target=ouvrir) for _ in range(n)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    return erreurs


def test_des_threads_ouvrent_ensemble_une_base_neuve_sans_database_is_locked(tmp_path):
    erreurs = [e for essai in range(30)
               for e in _ouvrir_ensemble(tmp_path / f"essai{essai}" / "tickets.db")]
    assert erreurs == []
