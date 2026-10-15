# [desc] DÉTECTION → ÉVÉNEMENT : ce que le watchdog et le hook de fin d'agent constatent sur un run (question posée, réponse, fin de run, process mort, lancement figé), traduit en transitions de ticket_fsm. Jamais appelé par une lecture. [/desc]
"""Le pont entre ce qu'on OBSERVE d'un agent et l'état persisté de son ticket (spec §5.7, B1).

`liveness` classe un agent (process, IPC, session) ; ce module transforme ces constats en
ÉVÉNEMENTS que `ticket_fsm` applique. Deux appelants, et seulement eux :
  * le hook de fin d'agent (`POST …/completed`) → `fin_de_run` (`constats_fin`) ;
  * le watchdog (`wake.tick`) → `constater`, pour les tickets d'un état « en vol ».
Aucune lecture (GET) n'appelle ce module : une liste ou une fiche lit `ticket.state`, point.

`close_reasons.issue_de_fin` est la SEULE table qui dit livré / non livré / arrêté (C14)."""
from __future__ import annotations

import logging

from bouzecode.web_v2.services.horodatage import age_s

from ...runtime import deferred as web_deferred
from ...runtime import ipc
from ...runtime.runner import agent_fiche, agent_vivacite
from ..sessions import store
from . import _persistence, ticket_fsm
from .constats_fin import enfants_actifs, fin_de_run  # noqa: F401 — ré-export (API historique)
from .fsm import cycle_des_runs, etats, journal

_log = logging.getLogger(__name__)

#: Typologies read-only (routeur / observateur) : leur réponse est un rapport, pas un diff.
NON_CODING_TYPOLOGIES = frozenset({"manager", "monitor"})
#: Observations « process mort » CONSÉCUTIVES avant de conclure (un hoquet psutil n'est pas un crash).
MORTS_AVANT_CRASH = 2
#: Au-delà, un lancement est figé (serveur tué en plein provisionnement) : ~20 min au pire légitime.
LANCEMENT_FIGE_S = 1800
_EN_ATTENTE = ("awaiting_input", "awaiting_plan_validation")


def cloture_lue(agent, agent_id: str = "") -> tuple[str, bool]:
    """(close_reason, final_answer) de la session sur disque — retrouvée dans le parc même
    pour un agent DÉCHARGÉ (`agent` None) —, avec repli sur l'IPC quand la session est restée
    muette à la clôture (`{status: finished, close_reason}` dans state.json)."""
    from .liveness import _session_data
    data = _session_data(agent_id or agent.agent_id, agent)
    close_reason = data.get("close_reason") or ""
    ipc_dir = getattr(agent, "ipc_dir", "") or ""
    if not close_reason and ipc_dir:
        etat_ipc = ipc.read_state(ipc.from_dir(ipc_dir))
        if etat_ipc.get("status") == ipc.STATUS_FINISHED:
            close_reason = etat_ipc.get("close_reason") or ""
    return close_reason, bool(data.get("final_answer"))


def _finir(slug: str, ticket: dict, run: dict, agent) -> str | None:
    """Le run est mort (ou oisif) : sa clôture, lue sur disque, décide de la fin."""
    from .liveness import _session_path
    close_reason, final_answer = cloture_lue(agent, run["agent_id"])
    session = _session_path(run["agent_id"], agent)
    if close_reason == "final_answer_deferred" and web_deferred.exists(session):
        return None  # des vérifications différées restent à drainer : la fin viendra après
    return fin_de_run(slug, ticket["id"], run["agent_id"], close_reason, final_answer, "watchdog")


def _compter_une_mort(slug: str, ticket: dict, run: dict, mort: bool) -> int:
    """`dead_ticks` du run (persisté) : remis à 0 dès qu'il vit, +1 à chaque tick mort."""
    avant = int(run.get("dead_ticks") or 0)
    apres = avant + 1 if mort else 0
    if apres != avant:
        def _poser(t: dict) -> None:
            for r in t.get("runs") or []:
                if r.get("agent_id") == run["agent_id"]:
                    r["dead_ticks"] = apres
        _persistence._mutate(slug, ticket["id"], _poser)
    return apres


def _constater_un_run_local(slug: str, ticket: dict, run: dict) -> str | None:
    agent = agent_fiche.load_agent(str(run["agent_id"]))
    if agent is None:  # fiche déchargée : seule la session du parc dit comment il a fini
        from .liveness import _session_path
        if _compter_une_mort(slug, ticket, run, True) < MORTS_AVANT_CRASH:
            return None
        if _session_path(run["agent_id"], None).is_file():
            return _finir(slug, ticket, run, None)
        return ticket_fsm.appliquer(slug, ticket["id"], etats.CRASHED, "watchdog",
                                    agent_id=run["agent_id"], code="introuvable")["state"]
    statut = store.agent_status(agent).get("state")
    if statut in _EN_ATTENTE:
        _compter_une_mort(slug, ticket, run, False)
        if ticket["state"] == etats.RUNNING:
            return ticket_fsm.appliquer(slug, ticket["id"], etats.QUESTION_ASKED, "watchdog",
                                        agent_id=run["agent_id"])["state"]
        return None
    if ticket["state"] == etats.AWAITING_INPUT and statut in ("running", "starting"):
        return ticket_fsm.appliquer(slug, ticket["id"], etats.ANSWERED, "watchdog",
                                    agent_id=run["agent_id"])["state"]
    if run.get("state") == cycle_des_runs.RUN_AWAITING_CHILDREN:
        return None  # manager garé : c'est le réveil (`wake.process_wakes`) qui le relance
    vivant = agent_vivacite.is_running(agent) and statut != "idle"
    if _compter_une_mort(slug, ticket, run, not vivant) < (1 if statut == "idle" else MORTS_AVANT_CRASH):
        return None
    if statut == "idle" and not cloture_lue(agent)[0]:
        return None  # chaud et oisif sans clôture lisible : rien à conclure
    return _finir(slug, ticket, run, agent)


def _lancement_fige(slug: str, ticket: dict) -> bool:
    with _persistence._connect() as conn:
        dernier = journal.dernier(conn, slug, ticket["id"], (etats.LAUNCHED,))
    depuis = (dernier or {}).get("at") or ticket.get("created_at") or ""
    age = age_s(depuis)
    return age is not None and age > LANCEMENT_FIGE_S


def constater(slug: str, ticket: dict) -> str | None:
    """UN passage du watchdog sur un ticket en vol. Rend le nouvel état, ou None."""
    if ticket["state"] == etats.PROVISIONING:
        if _lancement_fige(slug, ticket):
            return ticket_fsm.appliquer(slug, ticket["id"], etats.LAUNCH_FAILED_EVENT, "watchdog",
                                        code="lancement_interrompu",
                                        message="serveur arrêté pendant la préparation")["state"]
        return None
    if ticket["state"] not in (etats.RUNNING, etats.AWAITING_INPUT):
        return None
    run = cycle_des_runs.run_courant(ticket)
    if run is None:
        return ticket_fsm.appliquer(slug, ticket["id"], etats.CRASHED, "watchdog",
                                    code="sans_run", message="aucun run ouvert")["state"]
    if str(run.get("kind") or "") == "remote":
        return None  # exécution Rundeck : suivie et close par `distant.suivi`
    return _constater_un_run_local(slug, ticket, run)


def a_constater(ticket: dict) -> bool:
    """Le watchdog a-t-il quelque chose à constater sur ce ticket ? Pur, zéro I/O."""
    return ticket.get("state") in (etats.PROVISIONING, etats.RUNNING, etats.AWAITING_INPUT)

