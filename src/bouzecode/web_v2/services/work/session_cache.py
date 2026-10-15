"""Le parc lu UNE fois par processus, pas une fois par requête.

Pourquoi ce module existe (mesuré, serveur réel, 3 passes) : `GET /api/todo`
coûtait 597-617 ms à chaque clic de filtre alors que la fenêtre demandée ne
change RIEN au travail (`fenetre=tout` : 516-587 ms). Le temps ne partait pas
dans le calcul mais dans le RECHARGEMENT des journaux de session : `LiveSource`
mémoïsait ses sessions dans l'instance, et la route fabrique une source neuve à
chaque requête — le cache était donc jeté avec la réponse. In-process : source
réutilisée 15-19 ms, source neuve 214-254 ms, soit un facteur ~15×.

Le cache vit donc ici, au niveau du module, partagé par toutes les requêtes.
Deux garde-fous pour qu'un cache long ne serve jamais du périmé :

  * le CHEMIN du journal est mémoïsé définitivement (le chemin d'un agent ne
    change pas de sa vie), ce qui paie `runner.load_agent` une seule fois ;
  * le CONTENU est réputé valable tant que le `mtime` du fichier n'a pas bougé.
    Un `os.stat` coûte quelques microsecondes là où relire et parser le journal
    coûte des millisecondes, et il garantit qu'un agent qui écrit est relu.

`stats()` expose les compteurs de lectures disque : c'est de l'instrumentation
produit, et c'est ce qui rend la performance testable par un COMPTEUR D'I/O
plutôt que par un chronomètre — un seuil de temps serait instable en CI.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

#  Un agent introuvable est mémoïsé BRIÈVEMENT : sans cela, deux interrogations
#  de suite repayeraient chacune un `load_agent` ; en le mémoïsant pour
#  toujours, un agent créé juste après resterait invisible.
_MANQUANT_TTL = 5.0

_VERROU = threading.RLock()
_CHEMINS: dict[str, str] = {}
_MANQUANTS: dict[str, float] = {}
_SESSIONS: dict[str, tuple[float, dict]] = {}
_TESTS: dict[str, bool] = {}
_COMPTEURS = {"loads": 0, "hits": 0}


def stats() -> dict:
    """Compteurs de lectures : `loads` = disque touché, `hits` = servi de mémoire."""
    with _VERROU:
        return dict(_COMPTEURS)


def vider() -> None:
    """Oublie tout (tests, ou parc modifié hors du processus)."""
    with _VERROU:
        _CHEMINS.clear()
        _MANQUANTS.clear()
        _SESSIONS.clear()
        _TESTS.clear()
        _COMPTEURS["loads"] = 0
        _COMPTEURS["hits"] = 0


def _agent(agent_id: str):
    """L'agent, relu au plus une fois par processus (et rarement s'il manque)."""
    from ...runtime.runner import agent_fiche

    with _VERROU:
        expire = _MANQUANTS.get(agent_id)
        if expire is not None and time.monotonic() < expire:
            _COMPTEURS["hits"] += 1
            return None
        _COMPTEURS["loads"] += 1
    agent = agent_fiche.load_agent(agent_id)
    with _VERROU:
        if agent is None:
            _MANQUANTS[agent_id] = time.monotonic() + _MANQUANT_TTL
        else:
            _MANQUANTS.pop(agent_id, None)
    return agent


def _chemin(agent_id: str) -> str:
    """Le journal de l'agent. Mémoïsé : ce chemin ne change jamais."""
    with _VERROU:
        connu = _CHEMINS.get(agent_id)
        if connu is not None:
            _COMPTEURS["hits"] += 1
            return connu
    agent = _agent(agent_id)
    chemin = str(getattr(agent, "session_path", "") or "") if agent else ""
    with _VERROU:
        if chemin or agent is not None:
            #  Un agent absent n'est pas mémoïsé ici : c'est `_MANQUANTS` qui
            #  porte son oubli, avec sa péremption.
            _CHEMINS[agent_id] = chemin
    return chemin


def _mtime(chemin: str) -> float:
    try:
        return Path(chemin).stat().st_mtime
    except OSError:
        return -1.0


def charger(agent_id: str) -> dict:
    """Le journal de session de l'agent, relu seulement s'il a changé."""
    if not agent_id:
        return {}
    chemin = _chemin(agent_id)
    if not chemin:
        return {}
    empreinte = _mtime(chemin)
    with _VERROU:
        garde = _SESSIONS.get(agent_id)
        if garde is not None and garde[0] == empreinte:
            _COMPTEURS["hits"] += 1
            return garde[1]
        _COMPTEURS["loads"] += 1
    from ..sessions import store

    charge = store.load_session_json(Path(chemin))
    session = charge if isinstance(charge, dict) else {}
    with _VERROU:
        _SESSIONS[agent_id] = (empreinte, session)
    return session


def est_test(agent_id: str) -> bool:
    """Vrai pour une conversation de TEST (PING/PONG, « Ticket normal »…).

    C'était la SECONDE lecture disque par ticket clos, pas mémoïsée du tout :
    `collect()` la payait pour chaque ticket, en plus du journal."""
    if not agent_id:
        return False
    with _VERROU:
        connu = _TESTS.get(agent_id)
        if connu is not None:
            _COMPTEURS["hits"] += 1
            return connu
    from ..sessions import category

    agent = _agent(agent_id)
    #  La catégorie se déduit du prompt d'ouverture : elle ne bouge plus ensuite.
    verdict = bool(agent is not None
                   and category.classify_agent(agent) == category.CATEGORY_TEST)
    if agent is not None:
        with _VERROU:
            _TESTS[agent_id] = verdict
    return verdict
