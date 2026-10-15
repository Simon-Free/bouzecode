# [desc] Au boot : chaque sous-agent interrompu par le redémarrage est SIGNALÉ à son parent (ou à l'humain) ; aucun agent n'est relancé d'office. [/desc]
"""Remplace l'ancienne reprise automatique `auto_resume` (spec ticketing §11, D4 ; principe B4).

Le serveur ne relance plus personne de lui-même. Pour chaque SOUS-AGENT (run `work` d'un ticket
dispatché par un manager, ou run `merge` hérité) mort sans clôture sur un ticket OUVERT, il émet
UN événement, une seule fois (drapeau persistant `run['interruption_signalee']`) :
  * parent vivant ou réveillable (livré proprement) → message mis en file pour lui : « ton enfant
    X a été interrompu par un redémarrage du serveur ; relance-le si besoin ». La file est livrée
    par le watchdog quand le parent a fini son tour : c'est un RÉVEIL, il décide ;
  * pas de parent vivant → signalement (outil Signaler côté serveur) : l'humain décide.
Un agent dont l'arrêt a été demandé (`arret.demande`) n'est pas signalé : son arrêt est voulu.
Best-effort : une erreur sur un run est journalisée et n'empêche jamais le boot."""
from __future__ import annotations

import logging

from bouzecode.web_v2.services.horodatage import maintenant_iso

from . import arret, file_messages, liveness, signalements, tickets, wake
from .fsm import etats

logger = logging.getLogger(__name__)

DRAPEAU = "interruption_signalee"
#  Un parent qui a clos proprement (`delivered`) attend d'être réveillé : il est joignable.
_PARENT_JOIGNABLE = liveness.ALIVE | {"delivered"}


def _est_sous_agent(ticket: dict, run: dict) -> bool:
    kind = str(run.get("kind", ""))
    if kind == "merge":
        return True
    return kind == "work" and wake.is_manager_parent(str(ticket.get("parent") or ""))


def _texte_pour_le_parent(slug: str, ticket: dict, agent_id: str) -> str:
    return (f"[Serveur] Ton enfant {agent_id} (ticket {ticket['id']} « {ticket.get('title', '')} ») "
            f"a été interrompu par un redémarrage du serveur ; relance-le si besoin "
            f"(MessageAgent(ticket_id=\"{ticket['id']}\", …) ou POST /api/projects/{slug}/tickets/"
            f"{ticket['id']}/runs). Rien n'a été relancé d'office.")


def _signaler(slug: str, ticket: dict, run: dict) -> str:
    """Émet l'événement et rend son destinataire (`agent_id` du parent, ou « signalement »)."""
    agent_id = str(run.get("agent_id") or "")
    parent = str(ticket.get("parent") or "")
    vivacite = (liveness.classify_agent_run({}, {"agent_id": parent})
                if wake.is_manager_parent(parent) else "")
    if vivacite in _PARENT_JOIGNABLE:
        file_messages.mettre_en_file(parent, _texte_pour_le_parent(slug, ticket, agent_id))
        return parent
    signalements.creer(
        "alerte", f"Sous-agent {agent_id} interrompu par un redémarrage du serveur",
        detail=f"Ticket {slug}/{ticket['id']} « {ticket.get('title', '')} ». Son parent "
               f"{parent or '(aucun)'} n'est pas joignable : rien n'a été relancé.",
        action_attendue=f"relancer si besoin : POST /api/projects/{slug}/tickets/{ticket['id']}/runs",
        agent_id=agent_id, parents=[parent] if parent else [], ticket_slug=slug,
        ticket_id=ticket["id"])
    return "signalement"


def _marquer(slug: str, ticket_id: str, agent_id: str, destinataire: str) -> None:
    trace = {"at": maintenant_iso("auto"), "a": destinataire}

    def _poser(frais: dict) -> None:
        for run in frais.get("runs") or []:
            if isinstance(run, dict) and run.get("agent_id") == agent_id:
                run[DRAPEAU] = trace
    tickets._mutate(slug, ticket_id, _poser)


def _a_signaler(ticket: dict, run: dict) -> bool:
    return (bool(run.get("agent_id")) and not run.get(DRAPEAU)
            and _est_sous_agent(ticket, run)
            and liveness.classify_agent_run(ticket, run) == "crashed")


def signaler_les_interruptions() -> list[dict]:
    """Passe de boot. Rend [{slug, ticket, agent_id, a}] des événements émis (logs, tests)."""
    emis: list[dict] = []
    for slug, ticket in tickets.all_tickets():
        if (ticket.get("state") in etats.CLOS or ticket.get("archived")
                or arret.demande(ticket, slug)):
            continue
        for run in [r for r in ticket.get("runs") or [] if isinstance(r, dict)]:
            if not _a_signaler(ticket, run):
                continue
            try:
                destinataire = _signaler(slug, ticket, run)
                _marquer(slug, ticket["id"], run["agent_id"], destinataire)
            except Exception:  # noqa: BLE001 — un run illisible ne bloque pas le boot
                logger.exception("signalement de l'interruption de %s impossible",
                                 run.get("agent_id"))
                continue
            emis.append({"slug": slug, "ticket": ticket["id"], "agent_id": run["agent_id"],
                         "a": destinataire})
    return emis
