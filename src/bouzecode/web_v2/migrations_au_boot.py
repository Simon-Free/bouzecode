# [desc] Migrations de boot des stores (tickets L2, runs validate hérités, tâches du Bureau) : jouées par create_app, mais jamais sur un store du VRAI HOME hors du serveur de référence. [/desc]
"""Migrations de boot, gardées.

Le 2026-10-06 à 08:54:02 (heure locale), un agent a lancé depuis son worktree
`python -c "from bouzecode.web_v2.app import create_app; a=create_app(); ...url_map..."` pour
lister les routes. `create_app()` jouait ses migrations de boot sans condition : le VRAI store
(`~/.bouzecode/web_v2/tickets/tickets.db`) est passé au format L2 (563 tickets) avec le code
d'un worktree, pendant que le serveur de production tournait l'ancien code. `HOME_ISO=1`, posé
par l'agent, n'est lu par personne.

Règle, alignée sur le watchdog (`wake.start_poller`) : une migration qui écrirait dans un store
du vrai HOME ne se joue que dans le serveur de RÉFÉRENCE (`app.main`, verrou de `reference`).
Un store hors du vrai HOME (tests : HOME jetable ; bac à sable) se migre comme avant. Le « vrai
HOME » d'un process de test est celui que `pytest_home_etanche` transmet (`BZ_TESTS_VRAI_HOME`).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

_log = logging.getLogger(__name__)


def vrai_home() -> Path:
    return Path(os.environ.get("BZ_TESTS_VRAI_HOME") or Path.home())


def _sous(chemin: Path, racine: Path) -> bool:
    chemin_norme = os.path.normcase(os.path.realpath(chemin))
    racine_norme = os.path.normcase(os.path.realpath(racine)).rstrip(os.sep) + os.sep
    return chemin_norme.startswith(racine_norme)


def store_du_vrai_home() -> bool:
    from .services.work import _persistence
    #  Le dossier ~/.bouzecode, pas le HOME entier : sous Windows le tmp système (donc les HOME
    #  jetables des tests) vit DANS le profil, sous AppData.
    from bouzecode.paths import data_dir
    return _sous(_persistence._db_path(), data_dir(home=vrai_home()))


def autorisees() -> bool:
    """Vrai si ce process peut migrer le store courant au boot."""
    from . import reference
    return reference.est_reference() or not store_du_vrai_home()


def jouer() -> bool:
    """Joue les migrations de boot si elles sont autorisées. Rend True si elles ont été jouées.

    Idempotentes, loggées, non destructives ; un échec ne bloque jamais le démarrage."""
    if not autorisees():
        from .services.work import _persistence
        _log.warning("migrations de boot NON jouées : %s est dans le vrai HOME et ce process "
                     "n'est pas le serveur de référence (create_app hors de main)",
                     _persistence._db_path())
        return False
    try:
        from .services.work import migrations
        migrations.migrer_le_store()
        migrations.migrate_legacy_validate_runs()
    except Exception:  # noqa: BLE001 — migration best-effort, ne bloque pas le boot
        _log.exception("migration du store des tickets a échoué au boot")
    #  Bureau : chaque ticket non archivé est enveloppé dans une tâche, puis ces tâches v1 sont
    #  DÉPLACÉES vers les lignes du Bureau (après, pour que les tâches créées à CE boot partent
    #  tout de suite). Idempotentes via leurs tables de liaison.
    try:
        from .services.work import tache_v1_migration, task_migration
        task_migration.migrate_tickets_into_tasks()
        tache_v1_migration.migrer_taches_v1()
    except Exception:  # noqa: BLE001 — migration best-effort, ne bloque pas le boot
        _log.exception("migrate_tickets_into_tasks a échoué au boot")
    return True
