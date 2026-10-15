# [desc] LA remise d'un message à un agent (fusion de sessions._livrer et messaging.send_to_ticket_agent) : livré à un agent au repos, mis en file pendant un tour, jamais « envoyé » ambigu. [/desc]
"""Une seule implémentation de « donner un message à un agent » (spec §5.2) : la route
`…/tickets/{id}/messages`, la route agent `/api/agents/{id}/messages`, la réponse à une
question et le Bureau y passent.

* agent au repos (fini, chaud oisif, en attente de réponse) : relancé avec le message
  (`continue_agent`, ou `resume_pending_agent` pour une question) → `{delivered: true}` ; le
  ticket repasse `running` par transition explicite (`runs_ticket.signaler`, appelé par le
  runtime) ;
* agent en plein tour (`running`, `starting`) : le message est déposé dans sa file et lu à sa
  prochaine frontière de tour → `{queued: true, queue_id, position}` ; `si_occupe` dit quoi faire
  sinon (`interrompre` : le tour est coupé ; `refuser` : 409 `running`) ;
* rien n'a pu être remis : `Refus` (`agent_missing` 404, `not_delivered` 409). Un message mis en
  file reste dans la file (`statut: non_livre` si son process meurt) : il n'est jamais perdu."""
from __future__ import annotations

from ....runtime import pending
from ....runtime.runner import agent_fiche, agent_processus, agent_reprise
from ...sessions import store
from .. import arret, awaiting, delivery, dispatch, file_messages, interruption, tickets
from .refus import Refus

FILE, INTERROMPRE, REFUSER = "file", "interrompre", "refuser"
EN_TOUR = ("running", "starting")
AVIS_D_ARRET = ("DEMANDE D'ARRÊT de ton parent : termine ce que tu as en main, rends ton "
                "rapport maintenant (FinalAnswer) et ne relance rien ; tu ne seras plus "
                "réveillé ensuite.\n\n")


def agent_ou_refus(agent_id: str):
    agent = agent_fiche.load_agent(agent_id)
    if agent is None:
        raise Refus("agent_missing", f"agent {agent_id} introuvable : son enregistrement a "
                    "disparu du parc d'agents. RIEN n'a été envoyé — restaure sa fiche (elle peut "
                    "être dans web_agents/_trash/) avant de réessayer.", 404, agent_id=agent_id)
    return agent


def agent_du_ticket(ticket: dict):
    """L'agent reprenable du ticket : celui de son run de travail le plus récent (à défaut, de
    son run le plus récent). 409 `pas_d_agent` si le ticket n'a jamais eu de run."""
    runs = [r for r in ticket.get("runs") or [] if isinstance(r, dict) and r.get("agent_id")]
    run = next((r for r in runs if r.get("kind") == "work"), None) or (runs[0] if runs else None)
    if run is None:
        raise Refus("pas_d_agent", "aucun agent à qui parler sur ce ticket : lance un run "
                    "(POST …/runs)", 409, state=ticket.get("state"))
    return agent_ou_refus(str(run["agent_id"]))


def _ticket_de(agent) -> tuple[str, dict | None]:
    slug, ticket_id = getattr(agent, "ticket_slug", "") or "", getattr(agent, "ticket_id", "") or ""
    return slug, (tickets.get_ticket(slug, ticket_id) if slug and ticket_id else None)


def _en_file(agent, texte: str, si_occupe: str, origine: str, etat: str) -> dict:
    if si_occupe == REFUSER:
        raise Refus("running", "l'agent tourne encore — attends la fin du tour (ou envoie en "
                    "file)", 409, state=etat)
    if not texte:
        raise Refus("texte_requis", "message vide : rien à mettre en file", 400)
    item = file_messages.mettre_en_file(agent.agent_id, texte, origine)
    rendu = {"ok": True, "queued": True, "delivered": False, "queue_id": item["id"],
             "position": item["position"], "en_tour": bool(item.get("boite"))}
    if item.get("boite"):
        if si_occupe == INTERROMPRE:
            rendu["interruption"] = interruption.interrompre(agent)
        return rendu
    livraison = file_messages.livrer_si_pret(agent.agent_id)  # le tour vient de finir
    if livraison is not None and not livraison.get("ok"):
        raise Refus(str(livraison.get("reason") or "non_livre"),
                    str(livraison.get("error") or "le message n'a pas été remis"), 409,
                    queue_id=item["id"])
    return rendu


def _au_repos(agent, texte: str, etat: str, slug: str, ticket: dict | None):
    """Relance un agent au repos ; rend ce que le runtime a lancé (None : rien n'est parti)."""
    if (not agent_processus.session_process_running(agent.session_path) and etat != "idle"
            and etat not in awaiting.AWAITING_STATES):
        dispatch.rehome_agent_cwd(agent)  # le worktree a pu être nettoyé depuis
    delivery.reopen_for_new_work(slug, (ticket or {}).get("id", ""))
    if etat in awaiting.AWAITING_STATES or pending.exists(agent.session_path):
        return agent_reprise.resume_pending_agent(agent, texte)
    return agent_reprise.continue_agent(agent, texte)


def remettre(agent, texte: str, si_occupe: str = FILE, origine: str = "",
             arreter: bool = False, commenter: bool = True,
             du_ticket: tuple[str, dict] | None = None) -> dict:
    """Remet `texte` à `agent`. Rend `{delivered: True}` ou `{queued: True, …}` ; lève `Refus`.
    `du_ticket` : (slug, ticket) quand l'appelant parle AU TICKET (sinon, celui de l'agent)."""
    slug, ticket = du_ticket or _ticket_de(agent)
    if arreter and ticket is not None:
        arret.poser(slug, ticket, "parent (MessageAgent)")
        texte = AVIS_D_ARRET + texte
    elif ticket is not None:
        arret.lever(slug, ticket)  # une consigne explicite est une nouvelle mission
    etat = store.agent_status(agent)["state"]
    if etat in EN_TOUR:
        rendu = _en_file(agent, texte, si_occupe, origine, etat)
    elif _au_repos(agent, texte, etat, slug, ticket) is None:
        raise Refus("not_delivered", "un process tourne déjà pour cette session : le message "
                    "n'a PAS été transmis. Interromps l'agent puis réessaie.", 409, state=etat)
    else:
        store.invalidate_status(agent.agent_id)
        rendu = {"ok": True, "delivered": True, "queued": False}
    if commenter and ticket is not None and texte:
        tickets.add_comment(slug, ticket, texte, True)
    return rendu
