# [desc] POST …/runs : un agent NEUF sur un ticket existant (lancer, relancer, `merge_fix` sur un conflit), asynchrone (202), isolation DU TICKET conservée (C8), 409 `deja_actif` sous verrou (C10). [/desc]
"""Spec §5.1 / §6.3. Le ticket passe `provisioning` sous verrou au moment de la demande : un
second POST concurrent lit cet état et reçoit 409 `deja_actif`. Le reste (ré-isolation du
worktree, spawn, run posé) part en fond ; le client suit l'état.

L'isolation est CELLE DU TICKET : la relance ne la devine plus depuis une liste légère (C8). Le
nouvel agent reçoit le prompt du ticket, le récapitulatif des runs précédents et, s'il est
donné, `prompt_suffix`."""
from __future__ import annotations

import copy
import logging
import threading

from ....runtime.runner import agent_creation, agent_fiche, agent_vivacite
from .. import dispatch, tickets
from ..fsm import etats
from ..isolation import SHARED
from . import creation, garde, validation
from .refus import Refus

_log = logging.getLogger(__name__)


def _recapitulatif(ticket: dict) -> str:
    lignes = []
    for run in reversed([r for r in ticket.get("runs") or [] if isinstance(r, dict)]):
        fin = run.get("end") or {}
        issue = "livré" if fin.get("delivered") else (fin.get("reason") or run.get("state") or "?")
        lignes.append(f"- run {run.get('seq', '?')} ({run.get('kind', 'work')}, agent "
                      f"{run.get('agent_id', '?')}) : {issue}")
    if not lignes:
        return ""
    return "\n\n[Runs précédents sur ce ticket]\n" + "\n".join(lignes)


def _prompt(ticket: dict, payload: dict) -> str:
    suffixe = str(payload.get("prompt_suffix") or "").strip()
    return ticket["prompt"] + _recapitulatif(ticket) + (f"\n\n{suffixe}" if suffixe else "")


def _profil(ticket: dict, project: dict, payload: dict) -> str:
    demande = validation.profil(payload.get("profile") or "", project["path"])
    if demande:
        return demande
    if ticket.get("profile"):
        return str(ticket["profile"])
    return dispatch.resolve_profile(str(payload.get("typology") or ticket.get("typology") or ""),
                                    project["path"], managed=dispatch.est_manage(ticket))


def _spawn(slug: str, ticket: dict, project: dict, profil: str, modele: str, kind: str,
           prompt: str):
    cwd = project["path"]
    isolation = ticket.get("isolation") or SHARED
    if isolation != SHARED:
        cwd = dispatch.reisolate(slug, ticket, project["path"])
    agent = agent_creation.create_agent(
        prompt, modele, cwd, profile=profil, parent=ticket.get("parent") or "",
        ticket_slug=slug, ticket_id=ticket["id"], run_kind=kind,
        worktree_root=cwd if cwd != project["path"] else "",
        base_venv=dispatch.base_venv_for(isolation, project["path"]))
    arret = tickets.add_run(slug, ticket, agent.agent_id, kind, modele,
                            typology=ticket.get("typology", ""))
    if arret:
        from ..taches_actions import _tuer
        _tuer(agent.agent_id)
    return agent


def _spawn_en_fond(*args) -> None:
    slug, ticket = args[0], args[1]
    try:
        _spawn(*args)
    except Exception as exc:  # noqa: BLE001 — thread : l'échec est GRAVÉ sur le ticket
        _log.exception("relance du ticket %s/%s en échec", slug, ticket["id"])
        dispatch.record_launch_failure(slug, ticket, str(exc))


def _constater_une_fin_deja_ecrite(slug: str, ticket: dict) -> dict:
    """Le run courant est fini (process parti, clôture écrite dans sa session) mais le watchdog
    ne l'a pas encore constaté (deux ticks morts) : la liste dit déjà « planté » et propose
    Relancer, que `set_launching` refusait (409 `deja_actif`) pendant ~15 s. La relance constate
    cette fin d'abord. Un process vivant ou sans clôture lisible n'est jamais conclu ici."""
    from .. import constats
    from ..fsm import cycle_des_runs
    run = cycle_des_runs.run_courant(ticket) if ticket.get("state") == etats.RUNNING else None
    agent = agent_fiche.load_agent(str(run.get("agent_id") or "")) if run else None
    if agent is None or agent_vivacite.is_running(agent):
        return ticket
    close_reason, final_answer = constats.cloture_lue(agent)
    if close_reason:
        constats.fin_de_run(slug, ticket["id"], agent.agent_id, close_reason, final_answer, "serveur")
    return tickets.get_ticket(slug, ticket["id"]) or ticket


def lancer(slug: str, ticket_id: str, payload: dict, actor: str = "utilisateur") -> dict:
    """Pose `provisioning` puis lance l'agent ; rend le corps 202 (`run`, `ticket`)."""
    project = creation.projet(slug)
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is None:
        raise Refus("ticket_inconnu", f"ticket inconnu : {ticket_id}", 404, ticket_id=ticket_id)
    if ticket.get("archived"):
        raise Refus("archive", "ticket archivé : désarchive-le avant de le relancer", 409,
                    state=ticket.get("state"))
    garde.exiger()
    ticket = _constater_une_fin_deja_ecrite(slug, ticket)
    profil = _profil(ticket, project, payload)
    modele = validation.modele(payload.get("model") or "") or str(ticket.get("model") or "")
    kind = "merge_fix" if ticket.get("state") == etats.CONFLICT else \
        str(payload.get("kind") or "work")
    if ticket.get("state") not in etats.ACTIFS:
        creation._collision(project, ticket.get("isolation") or SHARED,
                            tuple(r.get("agent_id") for r in ticket.get("runs") or []), profil)
    tickets.set_launching(slug, ticket, actor)  # DejaActif (409) / TransitionRefusee (409)
    prompt = _prompt(ticket, payload)
    args = (slug, ticket, project, profil, modele, kind, prompt)
    if payload.get("defer", True) is False:
        try:
            agent = _spawn(*args)
        except Exception as exc:
            dispatch.record_launch_failure(slug, ticket, str(exc))
            raise
        corps = {"key": f"agent/{agent.agent_id}", "agent_id": agent.agent_id}
    else:
        threading.Thread(target=_spawn_en_fond, args=(slug, copy.deepcopy(ticket), *args[2:]),
                         daemon=True,
                         name=f"relance-{ticket_id}").start()
        corps = {}
    frais = tickets.get_ticket(slug, ticket_id) or ticket
    from ..etat_ticket import vue
    return {**corps, **vue(frais), "launch_key": f"launching/{ticket_id}",
            "run": {"kind": kind, "profile": profil, "model": modele,
                    "isolation": frais.get("isolation") or SHARED},
            "ticket": {**frais, **vue(frais)}}
