# [desc] Les runs d'un ticket : lancement (`set_launching`), run posé (`add_run`, transition vers running), tour clos (`mark_run_completed`), vivacité attachée en mémoire. [/desc]
"""Poser un run, c'est faire passer le ticket à `running` : `add_run` choisit la transition qui
y mène depuis l'état courant (démarrage d'un lancement, reprise d'un agent livré ou arrêté,
réponse à une question, réouverture) et l'applique AVEC le run neuf, dans la même transaction.
Plus aucune purge de drapeau à la main : un ticket relancé ne garde rien de son cycle précédent
(C9), parce que son état EST la transition."""
from __future__ import annotations

from . import ticket_fsm
from ._persistence import _load_one, _mutate, _now
from .fsm import etats

#: Depuis chaque état, le pas suivant vers un run vivant (`running`).
_PAS_VERS_UN_RUN = {
    etats.PROVISIONING: etats.STARTED, etats.CREATED: etats.LAUNCHED,
    etats.LAUNCH_FAILED: etats.LAUNCHED, etats.CONFLICT: etats.LAUNCHED,
    etats.DELIVERED: etats.MESSAGE_SENT, etats.IDLE_NO_DELIVERY: etats.MESSAGE_SENT,
    etats.STOPPED: etats.MESSAGE_SENT, etats.RUNNING: etats.MESSAGE_SENT,
    etats.AWAITING_INPUT: etats.ANSWERED, etats.CLOSED: etats.REOPENED,
    etats.ABANDONED: etats.REOPENED,
}
_ARRIVENT_A_UN_RUN = (etats.STARTED, etats.MESSAGE_SENT, etats.ANSWERED)
ARRET_PREPARATION = "arret_preparation"


def _miroir(ticket: dict, frais: dict) -> None:
    ticket.clear()
    ticket.update(frais)


def set_launching(slug: str, ticket: dict, actor: str = "serveur") -> dict:
    """Le lancement est demandé : `launched` → `provisioning`, sous verrou. Lève `DejaActif`
    (409 `deja_actif`) si un run ou un lancement est déjà en vol (C10)."""
    frais = ticket_fsm.appliquer(slug, ticket["id"], etats.LAUNCHED, actor)
    _miroir(ticket, frais)
    return frais


def _poser_sans_reprendre(slug: str, ticket: dict, run: dict) -> None:
    """Arrêt demandé pendant la préparation : le run est inscrit TERMINÉ (la tâche montre
    l'agent arrêté), l'état reste `stopped` ; l'appelant arrête l'agent aussitôt."""
    run.update(state="ended", ended_at=_now(),
               end={"reason": ARRET_PREPARATION, "delivered": False, "final_answer": False,
                    "returncode": None})
    _miroir(ticket, _mutate(slug, ticket["id"], lambda t: t["runs"].insert(0, run)))


def add_run(slug: str, ticket: dict, agent_id: str, kind: str, model: str,
            typology: str = "", extra: dict | None = None, actor: str = "serveur") -> dict | None:
    """Pose le run et amène le ticket à `running`. Rend la raison de l'arrêt si l'utilisateur
    a arrêté la tâche pendant la préparation (le run est alors inscrit terminé, et c'est à
    l'appelant d'arrêter l'agent qu'il vient de créer), None sinon."""
    run = {"agent_id": agent_id, "kind": kind, "model": model, "started_at": _now(),
           "typology": typology, **(extra or {})}
    frais = _load_one(slug, ticket["id"])
    if frais is None:
        raise LookupError(f"ticket inconnu : {slug}/{ticket['id']}")
    raison = frais.get("state_reason") or {}
    if frais["state"] == etats.STOPPED and raison.get("code") == ARRET_PREPARATION:
        _poser_sans_reprendre(slug, ticket, run)
        return raison
    for _pas in range(6):
        evenement = _PAS_VERS_UN_RUN.get(frais["state"])
        if evenement is None:
            raise ticket_fsm.TransitionRefusee(frais, etats.STARTED)
        donnees = {"nouveau_run": run} if evenement in _ARRIVENT_A_UN_RUN else {}
        try:
            frais = ticket_fsm.appliquer(slug, ticket["id"], evenement, actor, **donnees)
        except ticket_fsm.TransitionRefusee:
            #  Un écrivain concurrent a fait avancer l'état entre la lecture et la transition :
            #  on relit et on recalcule le pas suivant depuis l'état réel.
            frais = _load_one(slug, ticket["id"]) or frais
            continue
        if evenement in _ARRIVENT_A_UN_RUN:
            break
    else:
        raise ticket_fsm.TransitionRefusee(frais, etats.STARTED)
    _miroir(ticket, frais)
    return None


def mark_run_completed(slug: str, ticket: dict, agent_id: str) -> None:
    """Le run de `agent_id` a clos un tour proprement : `completed` et `turns` +1. `turns` est
    LA différence observable entre « rien n'a bougé » et « l'enfant a re-livré » (signature
    de réveil du parent). N'écrit pas l'état : la fin du run est une transition (`run_ended`)."""
    def _apply(t: dict) -> bool:
        changed = False
        for run in t.get("runs") or []:
            if isinstance(run, dict) and run.get("agent_id") == agent_id:
                run["completed"] = True
                run["turns"] = int(run.get("turns") or 0) + 1
                changed = True
        return changed
    frais = _mutate(slug, ticket["id"], _apply)
    if frais is not None:
        _miroir(ticket, frais)


def _vivacite(run: dict, done_agent: str, agents_index: dict | None) -> str:
    from ...runtime.runner import agent_fiche
    from ..sessions import store
    from .distant import runs as runs_distants
    if runs_distants.est_distant(run):
        return runs_distants.etat(run)
    if done_agent and run.get("agent_id") == done_agent:
        return "finished"
    agent_id = str(run.get("agent_id") or "")
    agent = agents_index.get(agent_id) if agents_index is not None else agent_fiche.load_agent(agent_id)
    return store.agent_status(agent)["state"] if agent else "disparu"


def refresh_run_states(slug: str, tickets: list[dict], done_agent: str = "",
                       agents_index: dict | None = None) -> None:
    """Attache EN MÉMOIRE la vivacité constatée de chaque run (`live_state`, `key`) — un
    affichage, jamais persisté (C3), jamais lu pour décider d'un état."""
    for ticket in tickets:
        for run in ticket.get("runs") or []:
            if isinstance(run, dict) and run.get("agent_id"):
                run["live_state"] = _vivacite(run, done_agent, agents_index)
                run["key"] = f"agent/{run['agent_id']}"


def signaler(slug: str, ticket_id: str, agent_id: str, quoi: str) -> str | None:
    """Ce que le runtime vient de FAIRE à un agent, traduit en transition de son ticket :
    `message` (reprise chaude : un agent livré, arrêté ou garé repart → `running`, C2),
    `reponse` (réponse poussée à une question → `running`), `arret` (agent tué → `stopped`).
    Rend le nouvel état, ou None si rien n'avait à bouger."""
    from .fsm import cycle_des_runs
    ticket = _load_one(slug, ticket_id) if slug and ticket_id else None
    if ticket is None:
        return None
    state, courant = ticket["state"], cycle_des_runs.run_courant(ticket)
    est_le_courant = courant is not None and courant.get("agent_id") == agent_id
    if quoi == "arret":
        if state == etats.PROVISIONING or (state in (etats.RUNNING, etats.AWAITING_INPUT)
                                           and est_le_courant):
            return ticket_fsm.appliquer(slug, ticket_id, etats.STOP, "utilisateur",
                                        agent_id=agent_id, code="killed")["state"]
        return None
    if quoi == "reponse":
        if state == etats.AWAITING_INPUT:
            return ticket_fsm.appliquer(slug, ticket_id, etats.ANSWERED, "serveur",
                                        agent_id=agent_id)["state"]
        return None
    if state in etats.CLOS:
        ticket = ticket_fsm.appliquer(slug, ticket_id, etats.REOPENED, "serveur")
        state = ticket["state"]
    garde = (state == etats.RUNNING and est_le_courant
             and courant.get("state") == cycle_des_runs.RUN_AWAITING_CHILDREN)
    if state in (etats.DELIVERED, etats.IDLE_NO_DELIVERY, etats.STOPPED) or garde:
        return ticket_fsm.appliquer(slug, ticket_id, etats.MESSAGE_SENT, "serveur",
                                    agent_id=agent_id)["state"]
    return None
