# [desc] Préchauffage des caches au démarrage du serveur, dans un thread de fond : index des sessions, arbre des agents, pastilles, profils. [/desc]
"""Le premier affichage après un démarrage payait tous les caches à froid : l'index de méta des
sessions (13,7 s mesurées sous Windows pour le premier listing), l'arbre des agents et la
vivacité de chacun, les pastilles de navigation, les profils YAML. Ce module les remplit dans
un thread démon lancé par `main()` juste avant de servir : le serveur répond tout de suite, et
la première page trouve des caches chauds au lieu de les payer.

Chaque étape est indépendante : une erreur est journalisée et n'empêche pas les suivantes.
Rien n'est écrit que les caches eux-mêmes. Opt-out : `BOUZECODE_PRECHAUFFAGE=0`. Jamais lancé
par `create_app()` (les tests en créent des centaines).
"""
from __future__ import annotations

import logging
import os
import threading
import time

_log = logging.getLogger(__name__)


def _index_des_sessions():
    from .services.sessions import listing_cache
    listing_cache.cached_list_sessions(include_tests=False)


#  Première page demandée par la page Agents (`PAGE` de static/js/conversations/list.js) : le
#  cache de l'arbre est indexé par (offset, limit), l'arbre complet ne la sert pas.
PREMIERE_PAGE = 40


def _arbre_des_agents():
    from .services.work import fleet
    fleet.agent_tree()
    fleet.agent_tree(offset=0, limit=PREMIERE_PAGE)


def _pastilles():
    from .services.work import inbox
    inbox.compteurs()


def _profils():
    from .services import typologies
    typologies.list_typologies()


#  Les pastilles AVANT l'arbre : elles calculent la boîte « À traiter » et les lignes du Bureau
#  (page d'accueil, demandée la première), alors que l'arbre avec git — des dizaines de
#  sous-process — ne sert que la page Agents.
ETAPES = (("index des sessions", _index_des_sessions), ("pastilles de navigation", _pastilles),
          ("arbre des agents", _arbre_des_agents), ("profils", _profils))


def prechauffer(etapes=ETAPES) -> dict[str, float | str]:
    """Joue chaque étape ; rend {étape: secondes, ou message d'erreur}."""
    bilan: dict[str, float | str] = {}
    for nom, etape in etapes:
        debut = time.monotonic()
        try:
            etape()
        except Exception as exc:  # noqa: BLE001 — un cache froid n'est pas une panne
            bilan[nom] = f"{type(exc).__name__}: {exc}"
            _log.warning("préchauffage « %s » en échec : %s", nom, exc)
            continue
        bilan[nom] = round(time.monotonic() - debut, 3)
    _log.info("préchauffage terminé : %s", bilan)
    return bilan


def lancer(etapes=ETAPES) -> threading.Thread | None:
    """Démarre le préchauffage en fond ; None si désactivé par `BOUZECODE_PRECHAUFFAGE=0`."""
    if os.environ.get("BOUZECODE_PRECHAUFFAGE", "1") == "0":
        return None
    fil = threading.Thread(target=prechauffer, args=(etapes,), name="prechauffage", daemon=True)
    fil.start()
    return fil
