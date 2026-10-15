# [desc] Un agent qui clôt son tour a-t-il RELU ses sous-agents ? Compare la fin de SON tour (écrite par le process dans son IPC) à celle de chaque enfant : indépendant de l'ordre dans lequel le watchdog visite les tickets. [/desc]
"""Garer ou non un agent délégant à la fin de son tour (run `awaiting_children`).

Un agent qui délègue n'a fini que s'il a relu le travail de ses enfants, donc si son dernier
TOUR s'est clos APRÈS leur fin. On compare des instants écrits par les process eux-mêmes
(`fin_de_tour` / `updated_at` de l'IPC à l'état `idle` ou `finished`), jamais l'heure d'un
constat : le watchdog visite les tickets dans un ordre quelconque et constate la mort d'un
process bien après sa dernière réponse (E2E du 2026-09-24 : tâche « À vérifier » neuf secondes
avant que le manager soit réveillé pour relire ses lots)."""
from __future__ import annotations

import math

from bouzecode.web_v2.services.horodatage import cle_chrono

from ...runtime.runner import agent_etat, agent_fiche, agent_vivacite
from ..sessions import store
from . import _persistence
from .fsm import cycle_des_runs, etats

#: Un enfant dont on ne sait pas quand il a fini (encore au travail, fiche introuvable).
EN_COURS = math.inf


def _instant(iso: str) -> float:
    return cle_chrono(iso)


def fin_du_dernier_tour(agent) -> float:
    """Instant (epoch) où `agent` a clos son dernier tour ; 0.0 s'il n'en sait rien.
    `finished_at` (mort CONSTATÉE par le serveur) n'est qu'un repli."""
    etat_ipc = agent_etat.get_ipc_state(agent) if getattr(agent, "ipc_dir", "") else {}
    if etat_ipc.get("status") in ("idle", "finished"):
        fin = float(etat_ipc.get("fin_de_tour") or etat_ipc.get("updated_at") or 0.0)
        if fin:
            return fin
    return _instant(str(getattr(agent, "finished_at", "") or ""))


def _fin_de_l_enfant(enfant: dict) -> float:
    """Fin du travail d'un ticket enfant : `EN_COURS` tant que son agent travaille."""
    run = cycle_des_runs.run_courant(enfant) or next(iter(enfant.get("runs") or []), None)
    agent = agent_fiche.load_agent(str(run["agent_id"])) if run and run.get("agent_id") else None
    if agent is None:
        return EN_COURS if enfant.get("state") in etats.ACTIFS else 0.0
    if agent_vivacite.is_running(agent) and store.agent_status(agent).get("state") != "idle":
        return EN_COURS
    return fin_du_dernier_tour(agent)


def _enfants(agent_id: str) -> list[dict]:
    with _persistence._connect() as conn:
        lignes = conn.execute("SELECT slug, id FROM tickets WHERE json_extract(data, '$.parent')=?",
                              (agent_id,)).fetchall()
    enfants = (_persistence._load_one(slug, ident) for slug, ident in lignes)
    return [e for e in enfants if e is not None and (e.get("runs") or e["state"] in etats.ACTIFS)]


def enfants_non_relus(agent_id: str, enfants_actifs: bool) -> bool:
    """`agent_id` vient de clore un tour : un de ses enfants a-t-il fini APRÈS (ou travaille
    encore) ? Sans fin de tour connue, seuls les enfants encore actifs comptent."""
    agent = agent_fiche.load_agent(agent_id)
    fin_du_parent = fin_du_dernier_tour(agent) if agent is not None else 0.0
    if not fin_du_parent:
        return enfants_actifs
    return any(_fin_de_l_enfant(enfant) > fin_du_parent for enfant in _enfants(agent_id))
