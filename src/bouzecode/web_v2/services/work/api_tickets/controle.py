# [desc] Interrompre, arrêter, répondre : un agent (par son id) ou l'agent du ticket. Refus de l'OS → 502 `arret_refuse`, jamais un 200 `ok:false` ; arrêt et interruption idempotents. [/desc]
"""Spec §5.3 : `interrupt` annule doucement le tour en cours (escalade en kill si l'agent ne
cède pas, l'agent reste reprenable) ; `stop` arrête le process (ticket `stopped{killed}`, par
le runtime) ; `answer` répond à la question en attente (409 `pas_de_question` sinon).

Un geste sur un agent qui ne tourne plus est un no-op réussi (idempotence, §9)."""
from __future__ import annotations

from ....runtime import ipc
from ....runtime.runner import agent_arret, agent_fiche
from ...sessions import store
from .. import arret, awaiting, dispatch, interruption
from ..fsm import cycle_des_runs, etats
from . import remise
from .refus import Refus


def _refus_os(agent_id: str, erreur: str, **details) -> Refus:
    return Refus("arret_refuse", f"le système a refusé d'arrêter l'agent : {erreur}", 502,
                 agent_id=agent_id, **details)


def interrompre_agent(agent) -> dict:
    issue = interruption.interrompre(agent)
    if not issue.get("ok"):
        raise _refus_os(agent.agent_id, str(issue.get("error") or ""),
                        escalated=bool(issue.get("escalated")))
    return {"ok": True, "agent_id": agent.agent_id, "escalated": bool(issue.get("escalated"))}


def arreter_agent(agent, par: str = "utilisateur") -> dict:
    """Kill (estampillé « arrêté par le serveur ») ; la demande d'arrêt est journalisée sur
    son ticket : plus de réveil automatique."""
    rollback = interruption.stamp_before_kill(agent, ipc.STATUS_KILLED_BY_SERVER, "kill")
    issue = agent_arret.kill_agent(agent) or {}
    if issue.get("error"):
        rollback()
        raise _refus_os(agent.agent_id, str(issue["error"]))
    arret.demander(agent, par)
    store.invalidate_status(agent.agent_id)
    return {"ok": True, "agent_id": agent.agent_id}


def _run_vivant(ticket: dict):
    """L'agent du run ouvert du ticket (None si aucun run n'est en vol)."""
    if ticket.get("state") not in (etats.RUNNING, etats.AWAITING_INPUT):
        return None
    courant = cycle_des_runs.run_courant(ticket)
    return agent_fiche.load_agent(str(courant["agent_id"])) if courant else None


def interrompre_ticket(slug: str, ticket: dict) -> dict:
    agent = _run_vivant(ticket)
    if agent is None:
        raise Refus("pas_d_agent", "aucun agent ne travaille sur ce ticket", 409,
                    state=ticket.get("state"))
    return {**interrompre_agent(agent), "state": ticket.get("state")}


def arreter_ticket(slug: str, ticket: dict) -> dict:
    """Arrête le lancement en préparation ou l'agent du run ouvert ; no-op sinon."""
    if ticket.get("state") == etats.PROVISIONING:
        demarre = dispatch.arreter_la_preparation(slug, ticket)
        agent = agent_fiche.load_agent(demarre) if demarre else None
        if agent is not None:
            arreter_agent(agent)
        return {"ok": True, "agent_id": demarre, "state": etats.STOPPED}
    agent = _run_vivant(ticket)
    if agent is None:
        return {"ok": True, "agent_id": "", "state": ticket.get("state")}
    return {**arreter_agent(agent), "state": etats.STOPPED}


def repondre(ticket: dict, question_id: str = "", choix: str = "", texte: str = "") -> dict:
    """Réponse humaine à la question de l'agent (awaiting_input → running)."""
    agent = _run_vivant(ticket) if ticket.get("state") == etats.AWAITING_INPUT else None
    statut = store.agent_status(agent) if agent is not None else {}
    if agent is None or statut.get("state") not in awaiting.AWAITING_STATES:
        raise Refus("pas_de_question", "l'agent de ce ticket n'attend aucune réponse", 409,
                    state=ticket.get("state"))
    reponse = "\n".join(part for part in (str(choix or "").strip(), str(texte or "").strip())
                        if part)
    if not reponse:
        raise Refus("reponse_requise", "choice ou text requis", 400)
    rendu = remise.remettre(agent, reponse, si_occupe=remise.REFUSER, origine="")
    return {**rendu, "question_id": question_id or statut.get("question_id", "")}
