# [desc] Ménage du warm-pool : évince les process d'agents chauds en trop (LRU), chaque éviction journalisée avec sa règle et ses dates. [/desc]
"""Le SEUL chemin qui tue des process d'agents sans qu'un humain l'ait demandé.

Sorti de `fleet.py` : construire une vue et terminer des process sont deux gestes de nature
opposée, et les garder ensemble avait déjà eu un coût — ce ménage vivait DANS le calcul de
l'arbre, si bien qu'un simple `GET /api/agents/tree` tuait des process et que la cadence
d'éviction suivait le rythme de poll de l'interface (un onglet fermé = plus aucune éviction).

Il est aujourd'hui appelé explicitement : à la création d'un ticket lancé (moment causal — un dispatch
ajoute un process au parc) et à chaque tick du watchdog (pour couvrir « aucun dispatch pendant
des heures », justement le moment où libérer les process idle a le plus de sens).

Quatre garde-fous, chacun payé le 2026-09-29 :
  * SEUL le serveur de référence balaie (`SERVEUR_PRINCIPAL`, posé par `app.main`). Un script
    d'agent qui fait `create_app()` sur les vraies données (serveur de smoke sur le port 5099,
    mesure de perf) armait son propre watchdog et évinçait la flotte réelle avec son code de
    worktree, en parallèle du vrai serveur ;
  * un agent n'est compté chaud que si son pid est PROUVÉ être le sien (cmdline) : un pid
    recyclé désignait un process tiers, l'agent mort depuis juillet passait pour chaud et
    recevait un `cancel.flag` à chaque tick ;
  * l'activité est l'instant le plus récent RÉEL (UTC) parmi spawn, fin, sauvegarde de session
    et dernier état IPC — plus une comparaison de chaînes (cf. `warmpool`) ;
  * un agent dont le ticket est ouvert et le tour clos sans livraison garde son process.

Ré-exporté par `fleet` : les appelants gardent `fleet.sweep_warm_pool()` et `fleet.WARM_POOL_MAX`.
"""
from __future__ import annotations

import logging
from typing import Any

from bouzecode.web_v2.services.horodatage import maintenant

from ... import close_reasons
from ...runtime import kill_journal, warmpool
from ...runtime.runner import agent_arret, agent_chaud, agent_etat, agent_processus, agent_registre
from ..sessions import purge, store
from . import file_messages

_log = logging.getLogger(__name__)

# Nombre max d'agents WARM (process vivant idle) gardés simultanément. Au-delà,
# `sweep_warm_pool()` évince les plus anciens (LRU par last_activity) pour libérer
# les process et éviter une accumulation de bouzecode idle après reboot/usage intensif.
WARM_POOL_MAX = 8

# Vrai dans le SEUL process lancé par `python -m bouzecode.web_v2` (cf. `app.main`).
SERVEUR_PRINCIPAL = False


def sweep_warm_pool() -> list[str]:
    """Tue les process warm en trop et renvoie les agents évincés.

    Aucune info git n'est nécessaire : on ne construit que les champs lus par
    warmpool.decide_evictions. Chaque éviction laisse une ligne dans le journal des arrêts
    (règle, dates comparées, pid vérifié), puis `runner.kill_agent` y ajoute son issue."""
    # Garde-fou de PRODUCTION : sous pytest ce balayage est INERTE (cf.
    # `runner.destruction_permitted`) ; hors du serveur de référence aussi.
    if not (agent_arret.destruction_permitted() and SERVEUR_PRINCIPAL):
        return []
    deleted = purge.load_deleted()
    agents = [
        agent for agent in agent_registre.list_agents()
        if f"agent/{agent.agent_id}" not in deleted
    ]
    meta_by_key = {a["key"]: a for a in store.list_agent_sessions()}
    nodes = {
        agent.agent_id: _warm_pool_view(agent, meta_by_key.get(f"agent/{agent.agent_id}", {}))
        for agent in agents
    }
    now = maintenant()
    evict = set(warmpool.decide_evictions(list(nodes.values()), now, WARM_POOL_MAX))
    motifs = warmpool.decide_evictions_motivees(list(nodes.values()), now, WARM_POOL_MAX)
    killed = []
    for agent in agents:
        if agent.agent_id not in evict:
            continue
        details = {"motif": motifs.get(agent.agent_id, {"regle": "inconnue"}),
                   "maintenant": now.isoformat(), "pid_verifie": nodes[agent.agent_id]["warm"]}
        #  Un process qui n'a pas encore lu le message qu'on vient de lui pousser ne s'évince
        #  pas : le tuer maintenant perdrait ce message (cf. file_messages).
        if file_messages.message_non_lu(agent):
            kill_journal.journaliser("eviction_refusee", agent, raison="message_non_lu",
                                     **details)
            continue
        kill_journal.journaliser("eviction", agent, **details)
        try:
            agent_arret.kill_agent(agent)
        except Exception:
            # Un process déjà mort ou un handle refusé ne doit pas priver les AUTRES agents
            # en trop de leur éviction : psutil lève `psutil.Error(Exception)`, pas `OSError`.
            # Rien n'est avalé — `_log.exception` trace la stack et la boucle continue.
            _log.exception("sweep_warm_pool: éviction de %s impossible", agent.agent_id)
            continue
        killed.append(agent.agent_id)
    return killed


def _warm_pool_view(agent, meta: dict) -> dict[str, Any]:
    """Les seuls champs d'un agent que lit la politique d'éviction du warm-pool."""
    status = meta.get("status") or store.agent_status(agent)
    warm = agent_chaud.is_warm(agent) and agent_processus.pid_still_belongs_to(agent)
    ipc_state = agent_etat.get_ipc_state(agent) if warm else {}
    derniere = warmpool.latest_instant([
        agent.started_at, getattr(agent, "finished_at", ""), meta.get("saved_at", ""),
        ipc_state.get("updated_at"), ipc_state.get("fin_de_tour")])
    return {
        "agent_id": agent.agent_id,
        "parent": agent.parent or "",
        "state": status.get("state", ""),
        "warm": warm,
        "last_activity": derniere.isoformat() if derniere else "",
        "travail_en_cours": warm and _travail_en_cours(agent, meta),
    }


def _travail_en_cours(agent, meta: dict) -> bool:
    """Ticket OUVERT et dernier tour clos SANS livraison (refus du modèle, prose, coupure) :
    l'agent a encore à faire, l'évincer ne ferait que transformer un oisif en « planté »."""
    if meta.get("close_reason", "") in close_reasons.DELIVERY_CLOSE_REASONS:
        return False
    slug, ticket_id = getattr(agent, "ticket_slug", ""), getattr(agent, "ticket_id", "")
    if not (slug and ticket_id):
        return False
    from . import tickets  # local : `tickets` tire une grande partie des services
    ticket = tickets.get_ticket(slug, ticket_id)
    from .fsm import etats
    return bool(ticket) and not (ticket.get("state") in etats.CLOS or ticket.get("archived"))
