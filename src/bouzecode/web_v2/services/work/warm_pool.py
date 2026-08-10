# [desc] Ménage du warm-pool : évince les process d'agents chauds en trop (LRU). [/desc]
"""Le SEUL chemin qui tue des process d'agents sans qu'un humain l'ait demandé.

Sorti de `fleet.py` : construire une vue et terminer des process sont deux gestes de nature
opposée, et les garder ensemble avait déjà eu un coût — ce ménage vivait DANS le calcul de
l'arbre, si bien qu'un simple `GET /api/agents/tree` tuait des process et que la cadence
d'éviction suivait le rythme de poll de l'interface (un onglet fermé = plus aucune éviction).

Il est aujourd'hui appelé explicitement : au `POST /api/dispatch` (moment causal — un dispatch
ajoute un process au parc) et à chaque tick du watchdog (pour couvrir « aucun dispatch pendant
des heures », justement le moment où libérer les process idle a le plus de sens).

Ré-exporté par `fleet` : les appelants gardent `fleet.sweep_warm_pool()` et `fleet.WARM_POOL_MAX`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ...runtime import runner, warmpool
from ..sessions import purge, store

_log = logging.getLogger(__name__)

# Nombre max d'agents WARM (process vivant idle) gardés simultanément. Au-delà,
# `sweep_warm_pool()` évince les plus anciens (LRU par last_activity) pour libérer
# les process et éviter une accumulation de bouzecode idle après reboot/usage intensif.
WARM_POOL_MAX = 8


def sweep_warm_pool() -> list[str]:
    """Tue les process warm en trop (LRU) et renvoie les agents évincés.

    Ce ménage vivait dans le calcul du tree : un simple GET /api/agents/tree tuait
    donc des process, et la cadence d'éviction suivait le rythme de poll de l'UI (un
    onglet fermé = plus aucune éviction). Il est ici un geste EXPLICITE, appelable
    depuis un chemin d'écriture ou depuis le tick du watchdog. Aucune info git n'est
    nécessaire : on ne construit que les champs lus par warmpool.decide_evictions."""
    # Garde-fou de PRODUCTION : ce balayage est le seul chemin qui tue des process en
    # masse sans qu'un humain l'ait demandé. Sous pytest il est INERTE — un conftest qui
    # oublierait d'isoler le parc ne peut plus rien détruire. Justification du procédé :
    # cf. `runner.destruction_permitted`.
    if not runner.destruction_permitted():
        return []
    deleted = purge.load_deleted()
    agents = [
        agent for agent in runner.list_agents()
        if f"agent/{agent.agent_id}" not in deleted
    ]
    meta_by_key = {a["key"]: a for a in store.list_agent_sessions()}
    nodes = [
        _warm_pool_view(agent, meta_by_key.get(f"agent/{agent.agent_id}", {}))
        for agent in agents
    ]
    evict = set(warmpool.decide_evictions(nodes, datetime.now(timezone.utc), WARM_POOL_MAX))
    killed = []
    for agent in agents:
        if agent.agent_id not in evict:
            continue
        try:
            runner.kill_agent(agent)
        except Exception:
            # Un process déjà mort ou un handle refusé ne doit pas priver les AUTRES
            # agents en trop de leur éviction : on trace et on continue la boucle.
            # `except OSError` NE tenait PAS cette intention : `kill_agent` termine via
            # psutil, dont les erreurs (`AccessDenied`, `NoSuchProcess`) dérivent de
            # `psutil.Error(Exception)` et NON d'`OSError`. Elles traversaient donc le
            # except, remontaient jusqu'à `wake._sweep_warm_pool` et avortaient la boucle
            # ENTIÈRE : une seule éviction refusée et le warm-pool ne se vidait plus.
            # D'où `Exception` : l'intention porte sur TOUT échec d'un agent, pas sur une
            # famille d'exceptions choisie d'avance. Rien n'est avalé — `_log.exception`
            # trace la stack complète et la boucle continue.
            _log.exception("sweep_warm_pool: éviction de %s impossible", agent.agent_id)
            continue
        killed.append(agent.agent_id)
    return killed


def _warm_pool_view(agent, meta: dict) -> dict[str, Any]:
    """Les seuls champs d'un agent que lit la politique d'éviction du warm-pool."""
    status = meta.get("status") or store.agent_status(agent)
    return {
        "agent_id": agent.agent_id,
        "parent": agent.parent or "",
        "state": status.get("state", ""),
        "warm": runner.is_warm(agent),
        "last_activity": max(agent.started_at or "", getattr(agent, "finished_at", "") or "",
                             meta.get("saved_at", "")),
    }
